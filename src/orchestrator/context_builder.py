# context/context_builder.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from orchestrator.prioritizer import SignalGroup
from signals.models import FixSignal, Span, TextEdit


@dataclass(frozen=True)
class FileSnippet:
    file_path: str
    start_row: int
    end_row: int
    text: str


class ContextBuilder:
    """
    Read-only context assembler for agent groups.

    v1 features:
      - window snippet around each signal span (±N lines)
      - fix metadata + edits (if present)
      - imports context (simple heuristic: top-of-file import block)
      - enclosing function block (simple indentation heuristic)

    It does NOT:
      - apply edits
      - infer correctness
      - call an LLM
    """

    def __init__(
        self,
        *,
        repo_root: str | Path | None = None,
        window_lines: int = 20,
        max_file_bytes: int = 512_000,  # safety cap: 512KB per file read
    ) -> None:
        self._repo_root = Path(repo_root) if repo_root is not None else None
        self._window_lines = window_lines
        self._max_file_bytes = max_file_bytes

    def build_group_context(self, group: SignalGroup) -> dict[str, Any]:
        """
        Convert a SignalGroup into a structured dict suitable for LLM planning.

        Returns:
          {
            "group": {...},
            "signals": [ {... per-signal context ...} ]
          }
        """
        items: list[dict[str, Any]] = []

        for sig in group.signals:
            file_text, lines, file_error = self._read_file(sig.file_path)

            span = sig.span
            snippet = self._snippet_around_span(sig.file_path, lines, span) if lines else None
            imports = self._extract_import_block(sig.file_path, lines) if lines else None
            enclosing = self._extract_enclosing_function(sig.file_path, lines, span) if (lines and span) else None

            items.append(
                {
                    "signal": self._signal_metadata(sig, group_tool_id=group.tool_id),
                    "file_read_error": file_error,
                    "code_context": {
                        "window": snippet.__dict__ if snippet else None,
                        "imports": imports.__dict__ if imports else None,
                        "enclosing_function": enclosing.__dict__ if enclosing else None,
                    },
                    "fix_context": self._fix_metadata(sig),
                }
            )

        return {
            "group": {
                "tool_id": group.tool_id,
                "signal_type": group.signal_type.value,
                "group_size": len(group.signals),
            },
            "signals": items,
        }

    # ----------------------------
    # File reading and slicing
    # ----------------------------

    def _resolve_path(self, file_path: str) -> Path:
        p = Path(file_path)
        if p.is_absolute():
            return p
        if self._repo_root is None:
            return p
        return self._repo_root / p

    def _read_file(self, file_path: str) -> tuple[str | None, list[str] | None, str | None]:
        """
        Returns (file_text, lines, error).
        lines are 1-based in concept but stored as a 0-based list of strings.
        """
        path = self._resolve_path(file_path)
        try:
            data = path.read_bytes()
            if len(data) > self._max_file_bytes:
                return None, None, f"File too large to read safely ({len(data)} bytes)"
            text = data.decode("utf-8")
            # keepends=True so line reconstruction preserves exact text
            lines = text.splitlines(keepends=True)
            return text, lines, None
        except Exception as e:
            return None, None, str(e)

    def _snippet_around_span(
        self,
        file_path: str,
        lines: list[str],
        span: Optional[Span],
    ) -> Optional[FileSnippet]:
        if span is None:
            return None

        total = len(lines)
        start_row = max(1, span.start.row - self._window_lines)
        end_row = min(total, span.end.row + self._window_lines)

        # Convert rows (1-based) -> indices (0-based)
        snippet_text = "".join(lines[start_row - 1 : end_row])
        return FileSnippet(file_path=file_path, start_row=start_row, end_row=end_row, text=snippet_text)

    # ----------------------------
    # Imports context
    # ----------------------------

    def _extract_import_block(self, file_path: str, lines: list[str]) -> Optional[FileSnippet]:
        """
        v1 heuristic:
          - scan from top for consecutive import/from lines, allowing comments/blank lines
          - stop at first non-import "real code" line
        """
        if not lines:
            return None

        start = 1
        end = 0
        seen_import = False
        in_docstring = False

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
        
            if stripped.startswith(('"""', "'''")):
                in_docstring = not in_docstring
                continue
            
            if in_docstring == True:
                continue

            if stripped == "" or stripped.startswith("#"):
                # allow leading comments/blank lines before/within import block
                if not seen_import:
                    continue
                # once imports started, allow blank/comment lines and keep extending
                end = idx
                continue

            if stripped.startswith("import ") or stripped.startswith("from "):
                seen_import = True
                end = idx
                continue

            # first real non-import statement ends the import block
            break

        if not seen_import or end == 0:
            return None

        text = "".join(lines[start - 1 : end])
        return FileSnippet(file_path=file_path, start_row=start, end_row=end, text=text)

    # ----------------------------
    # Enclosing function context
    # ----------------------------

    def _extract_enclosing_function(
        self,
        file_path: str,
        lines: list[str],
        span: Span,
    ) -> Optional[FileSnippet]:
        """
        v1 heuristic (no AST):
          - walk upwards from span.start.row to find nearest 'def ' or 'async def '
          - record its indentation level
          - then include lines until indentation decreases to <= that level (and not blank/comment)
        """
        if not lines:
            return None

        target_row = span.start.row
        if target_row < 1 or target_row > len(lines):
            return None

        def_line_row: Optional[int] = None
        def_indent: Optional[int] = None

        # 1) find nearest enclosing def/async def above target
        for r in range(target_row, 0, -1):
            line = lines[r - 1]
            stripped = line.lstrip()
            if stripped.startswith("def ") or stripped.startswith("async def "):
                def_line_row = r
                def_indent = len(line) - len(stripped)
                break

        if def_line_row is None or def_indent is None:
            return None

        # 2) extend downwards until scope ends
        end_row = def_line_row
        for r in range(def_line_row + 1, len(lines) + 1):
            line = lines[r - 1]
            stripped = line.lstrip()

            # Keep blank lines/comments inside block
            if stripped.strip() == "" or stripped.startswith("#"):
                end_row = r
                continue

            indent = len(line) - len(stripped)

            # If indentation drops to <= def indent, block ended
            if indent <= def_indent and not stripped.startswith((")", "]", "}")):
                break

            end_row = r

        text = "".join(lines[def_line_row - 1 : end_row])
        return FileSnippet(file_path=file_path, start_row=def_line_row, end_row=end_row, text=text)

    # ----------------------------
    # Metadata shaping
    # ----------------------------

    def _signal_metadata(self, sig: FixSignal, *, group_tool_id: str) -> dict[str, Any]:
        span = None
        if sig.span is not None:
            span = {
                "start": {"row": sig.span.start.row, "column": sig.span.start.column},
                "end": {"row": sig.span.end.row, "column": sig.span.end.column},
            }

        return {
            "tool_id": group_tool_id,  # group tool (ruff/mypy/bandit); later store on signal
            "signal_type": sig.signal_type.value,
            "severity": sig.severity.value,
            "rule_code": sig.rule_code,
            "message": sig.message,
            "docs_url": sig.docs_url,
            "file_path": sig.file_path,
            "span": span,
        }

    def _fix_metadata(self, sig: FixSignal) -> dict[str, Any]:
        if sig.fix is None:
            return {"exists": False}

        edits = []
        for e in sig.fix.edits:
            edits.append(
                {
                    "span": {
                        "start": {"row": e.span.start.row, "column": e.span.start.column},
                        "end": {"row": e.span.end.row, "column": e.span.end.column},
                    },
                    "content": e.content,
                }
            )

        return {
            "exists": True,
            "applicability": sig.fix.applicability.value,
            "tool_message": sig.fix.message,
            "edits": edits,
        }


# -------------------------------------------------------------------------
# PSEUDOCODE PLACEHOLDERS FOR FUTURE
# -------------------------------------------------------------------------

def build_repo_context_index(repo_root: str) -> None:
    """
    FUTURE (pseudocode):
      - build lightweight index of symbols -> file locations for faster context gathering
      - options:
          - ripgrep-based on demand with caching
          - ctags-like index
          - tree-sitter / jedi symbol graph

    This helps MyPy/Bandit fixes that require cross-file understanding.
    """
    raise NotImplementedError
