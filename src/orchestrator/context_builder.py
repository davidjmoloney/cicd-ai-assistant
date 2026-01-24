# context/context_builder.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from orchestrator.edit_window_config import (
    EditWindowSpec,
    get_edit_window_spec,
)
from orchestrator.prioritizer import SignalGroup
from signals.models import FixSignal, Span, TextEdit


@dataclass(frozen=True)
class FileSnippet:
    file_path: str
    start_row: int
    end_row: int
    text: str


@dataclass(frozen=True)
class EditSnippet:
    """
    A code snippet specifically for LLM editing.

    Contains the snippet text plus metadata about where the error is located
    within the snippet, allowing precise replacement in the original file.
    """
    file_path: str
    start_row: int              # 1-based line number where snippet starts
    end_row: int                # 1-based line number where snippet ends (inclusive)
    text: str                   # The actual code snippet (with base indent stripped)
    original_text: str          # The original snippet text (with full indentation)
    error_line: int             # 1-based line number in ORIGINAL file where error is
    error_line_in_snippet: int  # 1-based position within snippet (e.g., 4 of 7)
    snippet_length: int         # Total lines in snippet
    base_indent: str            # The base indentation that was stripped (e.g., "    ")


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
        window_lines: int = 30,
        snippet_window_lines: int = 3,  # Lines on each side of error for edit snippets
        max_file_bytes: int = 512_000,  # safety cap: 512KB per file read
    ) -> None:
        self._repo_root = Path(repo_root) if repo_root is not None else None
        self._window_lines = window_lines
        self._snippet_window_lines = snippet_window_lines
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
        import logging
        import os

        debug_mode = os.getenv("DEBUG_MODE_ON", "false").lower() in ("true", "1", "yes")
        if debug_mode:
            logging.info(f"\n=== Building context for {len(group.signals)} signals ===")

        items: list[dict[str, Any]] = []

        for idx, sig in enumerate(group.signals, 1):
            if debug_mode:
                logging.info(f"\nSignal {idx}/{len(group.signals)}: {sig.file_path}:{sig.span.start.row if sig.span else '?'}")

            file_text, lines, file_error = self._read_file(sig.file_path)

            span = sig.span

            # Get edit window specification for this signal
            edit_spec = get_edit_window_spec(sig)

            # Build context window (always ±10 minimum)
            snippet = self._snippet_around_span(sig.file_path, lines, span) if lines else None

            # Build edit snippet based on signal type
            edit_snippet = self._build_edit_snippet_for_signal(sig, lines, span, edit_spec) if lines else None

            # Always gather standard context
            imports = self._extract_import_block(sig.file_path, lines) if lines else None
            enclosing = self._extract_enclosing_function(sig.file_path, lines, span) if (lines and span) else None
            try_except = self._extract_try_except_block(sig.file_path, lines, span) if (lines and span) else None

            items.append(
                {
                    "signal": self._signal_metadata(sig, group_tool_id=group.tool_id),
                    "file_read_error": file_error,
                    "code_context": {
                        "window": snippet.__dict__ if snippet else None,
                        "imports": imports.__dict__ if imports else None,
                        "enclosing_function": enclosing.__dict__ if enclosing else None,
                        "try_except_block": try_except.__dict__ if try_except else None,
                    },
                    "edit_snippet": edit_snippet.__dict__ if edit_snippet else None,
                    "edit_window_type": edit_spec.window_type,
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
        import logging
        import os

        path = self._resolve_path(file_path)

        # Debug logging
        debug_mode = os.getenv("DEBUG_MODE_ON", "false").lower() in ("true", "1", "yes")
        if debug_mode:
            logging.info(f"ContextBuilder: Reading file_path='{file_path}'")
            logging.info(f"  Resolved to: {path}")
            logging.info(f"  Repo root: {self._repo_root}")
            logging.info(f"  File exists: {path.exists()}")

        try:
            data = path.read_bytes()
            if len(data) > self._max_file_bytes:
                return None, None, f"File too large to read safely ({len(data)} bytes)"
            text = data.decode("utf-8")
            # keepends=True so line reconstruction preserves exact text
            lines = text.splitlines(keepends=True)

            if debug_mode:
                logging.info(f"  ✓ Successfully read {len(lines)} lines ({len(data)} bytes)")

            return text, lines, None
        except Exception as e:
            if debug_mode:
                logging.error(f"  ✗ Failed to read: {e}")
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

    def _build_edit_snippet_for_signal(
        self,
        signal: FixSignal,
        lines: list[str],
        span: Optional[Span],
        edit_spec: EditWindowSpec,
    ) -> Optional[EditSnippet]:
        """
        Build an edit snippet based on the signal's edit window specification.

        Reuses existing extract_*() functions and converts FileSnippet to EditSnippet.

        Args:
            signal: The FixSignal being processed
            lines: File lines
            span: Error location
            edit_spec: Edit window specification

        Returns:
            EditSnippet with position metadata for precise replacement
        """
        if span is None:
            return None

        file_path = signal.file_path

        # Use existing extraction functions based on window type
        if edit_spec.window_type == "function":
            file_snippet = self._extract_enclosing_function(file_path, lines, span)
            fallback_lines = 7
        elif edit_spec.window_type == "imports":
            file_snippet = self._extract_import_block(file_path, lines)
            fallback_lines = 3
        elif edit_spec.window_type == "try_except":
            file_snippet = self._extract_try_except_block(file_path, lines, span)
            fallback_lines = 5
        else:  # window_type == "lines"
            window_lines = max(edit_spec.lines, edit_spec.min_edit_lines)
            return self._build_line_based_snippet(file_path, lines, span, window_lines)

        # If extraction succeeded, convert to EditSnippet, otherwise fallback to line-based
        if file_snippet:
            return self._convert_to_edit_snippet(file_snippet, lines, span)
        else:
            return self._build_line_based_snippet(file_path, lines, span, fallback_lines)

    def _build_line_based_snippet(
        self,
        file_path: str,
        lines: list[str],
        span: Span,
        window_lines: int,
    ) -> EditSnippet:
        """Build a line-based edit snippet with ±N lines around error."""
        total = len(lines)
        error_line = span.start.row
        start_row = max(1, error_line - window_lines)
        end_row = min(total, error_line + window_lines)

        snippet_lines = lines[start_row - 1 : end_row]
        original_text = "".join(snippet_lines)
        base_indent = self._calculate_base_indent(snippet_lines)
        stripped_text = self._strip_base_indent(snippet_lines, base_indent)

        return EditSnippet(
            file_path=file_path,
            start_row=start_row,
            end_row=end_row,
            text=stripped_text,
            original_text=original_text,
            error_line=error_line,
            error_line_in_snippet=error_line - start_row + 1,
            snippet_length=end_row - start_row + 1,
            base_indent=base_indent,
        )

    def _convert_to_edit_snippet(
        self,
        file_snippet: FileSnippet,
        lines: list[str],
        span: Span,
    ) -> EditSnippet:
        """Convert a FileSnippet to EditSnippet with indent stripping and error tracking."""
        snippet_lines = lines[file_snippet.start_row - 1 : file_snippet.end_row]
        original_text = "".join(snippet_lines)
        base_indent = self._calculate_base_indent(snippet_lines)
        stripped_text = self._strip_base_indent(snippet_lines, base_indent)

        error_line = span.start.row
        error_line_in_snippet = error_line - file_snippet.start_row + 1
        snippet_length = file_snippet.end_row - file_snippet.start_row + 1

        return EditSnippet(
            file_path=file_snippet.file_path,
            start_row=file_snippet.start_row,
            end_row=file_snippet.end_row,
            text=stripped_text,
            original_text=original_text,
            error_line=error_line,
            error_line_in_snippet=error_line_in_snippet,
            snippet_length=snippet_length,
            base_indent=base_indent,
        )

    def _calculate_base_indent(self, lines: list[str]) -> str:
        """
        Calculate the base (minimum) indentation across non-empty lines.

        Returns the common leading whitespace that can be stripped from all lines.
        """
        min_indent: str | None = None

        for line in lines:
            # Skip empty lines or lines with only whitespace
            stripped = line.rstrip('\n\r')
            if not stripped.strip():
                continue

            # Calculate leading whitespace
            leading = stripped[:len(stripped) - len(stripped.lstrip())]

            if min_indent is None:
                min_indent = leading
            elif len(leading) < len(min_indent):
                min_indent = leading

        return min_indent or ""

    def _strip_base_indent(self, lines: list[str], base_indent: str) -> str:
        """
        Strip base indentation from all lines.

        Preserves relative indentation within the snippet.
        Empty lines are preserved as-is.
        """
        if not base_indent:
            return "".join(lines)

        indent_len = len(base_indent)
        result_lines = []

        for line in lines:
            # Preserve empty lines
            if not line.strip():
                result_lines.append(line)
            # Strip base indent if line starts with it
            elif line.startswith(base_indent):
                result_lines.append(line[indent_len:])
            else:
                # Line has less indent than base (shouldn't happen, but handle gracefully)
                result_lines.append(line.lstrip())

        return "".join(result_lines)

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
    # Try/except block context
    # ----------------------------

    def _extract_try_except_block(
        self,
        file_path: str,
        lines: list[str],
        span: Span,
    ) -> Optional[FileSnippet]:
        """
        v1 heuristic (no AST):
          - walk upwards from span.start.row to find nearest 'try:'
          - record its indentation level
          - then include lines until indentation decreases to <= that level
          - includes all except/else/finally blocks
        """
        if not lines:
            return None

        target_row = span.start.row
        if target_row < 1 or target_row > len(lines):
            return None

        try_line_row: Optional[int] = None
        try_indent: Optional[int] = None

        # 1) find nearest enclosing try: above target
        for r in range(target_row, 0, -1):
            line = lines[r - 1]
            stripped = line.lstrip()
            if stripped.startswith("try:"):
                try_line_row = r
                try_indent = len(line) - len(stripped)
                break

        if try_line_row is None or try_indent is None:
            return None

        # 2) extend downwards to include entire try/except/else/finally block
        end_row = try_line_row
        for r in range(try_line_row + 1, len(lines) + 1):
            line = lines[r - 1]
            stripped = line.lstrip()

            # Keep blank lines/comments inside block
            if stripped.strip() == "" or stripped.startswith("#"):
                end_row = r
                continue

            indent = len(line) - len(stripped)

            # Keep except/else/finally at same level as try
            if indent == try_indent and stripped.startswith(("except", "else:", "finally:")):
                end_row = r
                continue

            # If indentation drops to <= try indent (and not except/else/finally), block ended
            if indent <= try_indent and not stripped.startswith((")", "]", "}")):
                break

            end_row = r

        text = "".join(lines[try_line_row - 1 : end_row])
        return FileSnippet(file_path=file_path, start_row=try_line_row, end_row=end_row, text=text)

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


    # ----------------------------
    # PLACEHOLDERS: Future context gathering mechanisms
    # ----------------------------

    def _extract_class_definition(
        self,
        file_path: str,
        lines: list[str],
        span: Span,
    ) -> Optional[FileSnippet]:
        """
        PLACEHOLDER: Extract class definition for method errors.

        For mypy errors in class methods, this would extract:
        - Class signature (class Foo(Base):)
        - Type variables/generics
        - Class-level attributes with types
        - Parent class references

        To be implemented when needed for better method-level type error fixes.

        Returns:
            FileSnippet containing class definition or None
        """
        raise NotImplementedError("Class definition extraction not yet implemented")

    def _extract_type_aliases(
        self,
        file_path: str,
        lines: list[str],
    ) -> Optional[FileSnippet]:
        """
        PLACEHOLDER: Extract type alias definitions from a file.

        For mypy errors referencing custom types, this would extract:
        - Type alias definitions (MyType = Union[str, int])
        - TypedDict definitions
        - Protocol definitions
        - NewType definitions

        To be implemented when needed for better type error context.

        Returns:
            FileSnippet containing type aliases or None
        """
        raise NotImplementedError("Type alias extraction not yet implemented")

    def _extract_related_function_definitions(
        self,
        file_path: str,
        lines: list[str],
        function_name: str,
    ) -> Optional[FileSnippet]:
        """
        PLACEHOLDER: Extract function definition for cross-function references.

        For mypy arg-type/call-arg errors, this would find and extract
        the function signature being called, even if it's defined elsewhere
        in the file.

        Args:
            file_path: Path to file
            lines: File lines
            function_name: Name of function to find

        To be implemented when simple error messages aren't sufficient.

        Returns:
            FileSnippet containing function definition or None
        """
        raise NotImplementedError("Related function extraction not yet implemented")

    def _extract_module_constants(
        self,
        file_path: str,
        lines: list[str],
    ) -> Optional[FileSnippet]:
        """
        PLACEHOLDER: Extract module-level constants.

        For validation logic understanding, this would extract:
        - Module-level constant definitions
        - Enum definitions
        - Configuration constants

        To be implemented when needed for better validation-aware fixes.

        Returns:
            FileSnippet containing module constants or None
        """
        raise NotImplementedError("Module constant extraction not yet implemented")

    def _extract_parent_class_method(
        self,
        file_path: str,
        class_name: str,
        method_name: str,
        repo_root: str,
    ) -> Optional[FileSnippet]:
        """
        PLACEHOLDER: Extract parent class method definition.

        For mypy override errors, this would:
        1. Find the parent class definition (could be in another file)
        2. Extract the method signature being overridden
        3. Return both locations for comparison

        This is complex because it requires:
        - Import resolution
        - Cross-file symbol lookup
        - Potentially reading from installed packages

        To be implemented if override errors become common enough to warrant
        the complexity.

        Returns:
            FileSnippet containing parent method or None
        """
        raise NotImplementedError("Parent class method extraction not yet implemented")


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
