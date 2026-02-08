# context/context_builder.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from orchestrator.signal_requirements import (
    EditWindowSpec,
    get_edit_window_spec,
    get_context_requirements,
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

            # Get context requirements for this signal
            context_req = get_context_requirements(sig)

            # Gather base context only if required (optimize token usage)
            imports = None
            enclosing = None
            try_except = None

            if lines:
                if context_req.include_imports:
                    imports = self._extract_import_block(sig.file_path, lines)
                if context_req.include_enclosing_function and span:
                    enclosing = self._extract_enclosing_function(sig.file_path, lines, span)
                if context_req.include_try_except and span:
                    try_except = self._extract_try_except_block(sig.file_path, lines, span)

            # Gather additional specialized context based on signal requirements
            class_def = None
            type_aliases = None
            related_func = None
            module_constants = None

            if lines:
                if context_req.needs_class_definition and span:
                    class_def = self._extract_class_definition(sig.file_path, lines, span)
                if context_req.needs_type_aliases:
                    type_aliases = self._extract_type_aliases(sig.file_path, lines)
                if context_req.needs_related_functions and context_req.related_function_name:
                    related_func = self._extract_related_function_definitions(
                        sig.file_path, lines, context_req.related_function_name
                    )
                if context_req.needs_module_constants:
                    module_constants = self._extract_module_constants(sig.file_path, lines)

            items.append(
                {
                    "signal": self._signal_metadata(sig, group_tool_id=group.tool_id),
                    "file_read_error": file_error,
                    "code_context": {
                        "window": snippet.__dict__ if snippet else None,
                        "imports": imports.__dict__ if imports else None,
                        "enclosing_function": enclosing.__dict__ if enclosing else None,
                        "try_except_block": try_except.__dict__ if try_except else None,
                        "class_definition": class_def.__dict__ if class_def else None,
                        "type_aliases": type_aliases.__dict__ if type_aliases else None,
                        "related_function": related_func.__dict__ if related_func else None,
                        "module_constants": module_constants.__dict__ if module_constants else None,
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
        elif edit_spec.window_type == "class":
            file_snippet = self._extract_enclosing_class(file_path, lines, span)
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
          - include decorators above the function (e.g., @dataclass, @property)
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

        # 2) Include decorators above the function definition
        start_row = def_line_row
        for r in range(def_line_row - 1, 0, -1):
            line = lines[r - 1]
            stripped = line.lstrip()
            # Include decorators (@) and blank lines immediately before function
            if stripped.startswith("@") or stripped == "":
                start_row = r
            else:
                # Stop if we hit non-decorator, non-blank content
                break

        # 3) extend downwards until scope ends
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

        text = "".join(lines[start_row - 1 : end_row])
        return FileSnippet(file_path=file_path, start_row=start_row, end_row=end_row, text=text)

    def _extract_enclosing_class(
        self,
        file_path: str,
        lines: list[str],
        span: Span,
    ) -> Optional[FileSnippet]:
        """
        Extract the full enclosing class for a missing class docstring (D101).

        Similar to _extract_enclosing_function but for classes:
          - Walk upwards to find nearest 'class ' statement
          - Include decorators above the class (e.g., @dataclass)
          - Extend downwards until indentation drops to class level

        Args:
            file_path: Path to the file
            lines: File lines
            span: Error location

        Returns:
            FileSnippet containing full class or None
        """
        if not lines:
            return None

        target_row = span.start.row
        if target_row < 1 or target_row > len(lines):
            return None

        class_line_row: Optional[int] = None
        class_indent: Optional[int] = None

        # 1) Find nearest enclosing class above target
        for r in range(target_row, 0, -1):
            line = lines[r - 1]
            stripped = line.lstrip()
            if stripped.startswith("class "):
                class_line_row = r
                class_indent = len(line) - len(stripped)
                break

        if class_line_row is None or class_indent is None:
            return None

        # 2) Include decorators above the class definition
        start_row = class_line_row
        for r in range(class_line_row - 1, 0, -1):
            line = lines[r - 1]
            stripped = line.lstrip()
            # Include decorators (@) and blank lines immediately before class
            if stripped.startswith("@") or stripped == "":
                start_row = r
            else:
                # Stop if we hit non-decorator, non-blank content
                break

        # 3) Extend downwards until scope ends
        end_row = class_line_row
        for r in range(class_line_row + 1, len(lines) + 1):
            line = lines[r - 1]
            stripped = line.lstrip()

            # Keep blank lines/comments inside block
            if stripped.strip() == "" or stripped.startswith("#"):
                end_row = r
                continue

            indent = len(line) - len(stripped)

            # If indentation drops to <= class indent, block ended
            if indent <= class_indent and not stripped.startswith((")", "]", "}")):
                break

            end_row = r

        text = "".join(lines[start_row - 1 : end_row])
        return FileSnippet(file_path=file_path, start_row=start_row, end_row=end_row, text=text)

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
        Extract nearest enclosing try/except block within the same function scope.

        Walks upwards to find 'try:', but stops at function/class boundaries
        to avoid returning try blocks from different functions.
        """
        if not lines:
            return None

        target_row = span.start.row
        if target_row < 1 or target_row > len(lines):
            return None

        # Find the starting indentation level to detect scope boundaries
        start_indent: Optional[int] = None
        for r in range(target_row, 0, -1):
            line = lines[r - 1]
            stripped = line.lstrip()
            if stripped and not stripped.startswith("#"):
                start_indent = len(line) - len(stripped)
                break

        if start_indent is None:
            return None

        try_line_row: Optional[int] = None
        try_indent: Optional[int] = None

        # Walk upwards to find nearest enclosing try:
        for r in range(target_row, 0, -1):
            line = lines[r - 1]
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            # Stop if we hit a function definition at same/lower indent
            # This means we've left the current function scope
            if (stripped.startswith("def ") or stripped.startswith("async def ")) and indent <= start_indent:
                break

            # Stop if we hit a class definition at same/lower indent
            # This means we've left the current class scope
            if stripped.startswith("class ") and indent <= start_indent:
                break

            if stripped.startswith("try:"):
                try_line_row = r
                try_indent = len(line) - len(stripped)
                break

        if try_line_row is None or try_indent is None:
            return None

        # Extend downwards to include entire try/except/else/finally block
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

        # Verify that the target line is actually inside the try/except block
        # If the target is below the block, this isn't an enclosing try
        if target_row > end_row:
            return None

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
            "tool_id": group_tool_id,  # group tool (ruff/mypy/pydocstyle); later store on signal
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
        Extract class definition for method errors.

        Finds the enclosing class by walking upwards to find 'class ' statement,
        then extracts just the class header including:
        - Class signature (class Foo(Base):)
        - Decorators on the class
        - Docstring (first line only)
        - Class-level variable annotations (without implementations)

        Args:
            file_path: Path to the file
            lines: File lines
            span: Error location

        Returns:
            FileSnippet containing class definition header or None
        """
        if not lines:
            return None

        target_row = span.start.row
        if target_row < 1 or target_row > len(lines):
            return None

        class_line_row: Optional[int] = None
        class_indent: Optional[int] = None

        # 1) Find nearest enclosing class above target
        for r in range(target_row, 0, -1):
            line = lines[r - 1]
            stripped = line.lstrip()
            if stripped.startswith("class "):
                class_line_row = r
                class_indent = len(line) - len(stripped)
                break

        if class_line_row is None or class_indent is None:
            return None

        # 2) Include decorators above class
        start_row = class_line_row
        for r in range(class_line_row - 1, 0, -1):
            line = lines[r - 1]
            stripped = line.lstrip()
            # Include decorators and blank lines
            if stripped.startswith("@") or stripped == "":
                start_row = r
            else:
                break

        # 3) Extract class header (class line + docstring if present)
        end_row = class_line_row
        in_docstring = False
        docstring_quote = None

        for r in range(class_line_row + 1, min(class_line_row + 20, len(lines) + 1)):
            line = lines[r - 1]
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            # Check for docstring start
            if not in_docstring and (stripped.startswith('"""') or stripped.startswith("'''")):
                docstring_quote = stripped[:3]
                in_docstring = True
                end_row = r
                # Check if docstring ends on same line
                if stripped.count(docstring_quote) >= 2:
                    in_docstring = False
                    break
                continue

            # Check for docstring end
            if in_docstring:
                if docstring_quote in stripped:
                    end_row = r
                    break
                end_row = r
                continue

            # Include class-level annotations
            if indent > class_indent and ":" in stripped and "=" not in stripped:
                end_row = r
                continue

            # Stop at first method or code at class level
            if indent > class_indent:
                break

            # Stop if we hit another class/def at same level
            if indent == class_indent and (stripped.startswith("def ") or stripped.startswith("class ")):
                break

        text = "".join(lines[start_row - 1 : end_row])
        return FileSnippet(file_path=file_path, start_row=start_row, end_row=end_row, text=text)

    def _extract_type_aliases(
        self,
        file_path: str,
        lines: list[str],
    ) -> Optional[FileSnippet]:
        """
        Extract type alias definitions from a file.

        Scans the file for module-level type definitions:
        - Type alias assignments (MyType = Union[str, int])
        - TypedDict classes
        - Protocol classes
        - NewType calls
        - TypeVar definitions

        Args:
            file_path: Path to the file
            lines: File lines

        Returns:
            FileSnippet containing all type aliases or None if none found
        """
        if not lines:
            return None

        type_alias_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Skip empty lines, comments, imports, and docstrings
            if not stripped or stripped.startswith("#") or stripped.startswith(("import ", "from ")):
                i += 1
                continue

            # Check for type alias patterns (at module level, indent = 0)
            if line and line[0] not in (' ', '\t'):
                # TypeVar, NewType, type aliases with Union/Optional/etc
                if any(keyword in stripped for keyword in ["TypeVar(", "NewType(", "Union[", "Optional[", "Literal[", "TypeAlias"]):
                    type_alias_lines.append((i + 1, line))

                # TypedDict class definition
                elif stripped.startswith("class ") and "TypedDict" in stripped:
                    # Include the full TypedDict class
                    start = i + 1
                    class_lines = [line]
                    i += 1
                    while i < len(lines):
                        next_line = lines[i]
                        # Continue if indented or blank
                        if next_line and (next_line[0] in (' ', '\t') or next_line.strip() == ""):
                            class_lines.append(next_line)
                            i += 1
                        else:
                            break
                    type_alias_lines.append((start, "".join(class_lines)))
                    continue

                # Protocol class definition
                elif stripped.startswith("class ") and "Protocol" in stripped:
                    # Include just the class signature
                    type_alias_lines.append((i + 1, line))

            i += 1

        if not type_alias_lines:
            return None

        # Combine all type aliases into a snippet
        start_row = type_alias_lines[0][0]
        end_row = type_alias_lines[-1][0]
        text = "".join(alias_text for _, alias_text in type_alias_lines)

        return FileSnippet(file_path=file_path, start_row=start_row, end_row=end_row, text=text)

    def _extract_related_function_definitions(
        self,
        file_path: str,
        lines: list[str],
        function_name: str,
    ) -> Optional[FileSnippet]:
        """
        Extract function definition for cross-function references.

        Searches for a function by name and extracts just its signature
        (the def line with parameters and return type).

        Args:
            file_path: Path to file
            lines: File lines
            function_name: Name of function to find

        Returns:
            FileSnippet containing function signature or None
        """
        if not lines or not function_name:
            return None

        # Search for function definition
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            # Look for def function_name( or async def function_name(
            if stripped.startswith(f"def {function_name}(") or stripped.startswith(f"async def {function_name}("):
                start_row = i + 1

                # Extract full signature (might span multiple lines)
                signature_lines = [line]
                j = i + 1

                # Continue if line doesn't end with ):
                while j < len(lines) and not signature_lines[-1].rstrip().endswith(":"):
                    signature_lines.append(lines[j])
                    j += 1

                end_row = j
                text = "".join(signature_lines)
                return FileSnippet(file_path=file_path, start_row=start_row, end_row=end_row, text=text)

        return None

    def _extract_module_constants(
        self,
        file_path: str,
        lines: list[str],
    ) -> Optional[FileSnippet]:
        """
        Extract module-level constants.

        Finds module-level constant assignments, typically:
        - UPPER_CASE variable assignments
        - Enum class definitions
        - Configuration dictionaries/lists

        Args:
            file_path: Path to the file
            lines: File lines

        Returns:
            FileSnippet containing module constants or None
        """
        if not lines:
            return None

        constant_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Skip empty lines, comments, imports
            if not stripped or stripped.startswith("#") or stripped.startswith(("import ", "from ", "def ", "class ", "async def")):
                i += 1
                continue

            # Check for module-level assignments (indent = 0)
            if line and line[0] not in (' ', '\t'):
                # UPPER_CASE constants
                if "=" in stripped:
                    var_name = stripped.split("=")[0].strip().rstrip(":")
                    # Check if it's an UPPER_CASE name (constant convention)
                    if var_name.isupper() and var_name.replace("_", "").isalnum():
                        constant_lines.append((i + 1, line))

            i += 1

        if not constant_lines:
            return None

        # Combine all constants into a snippet
        start_row = constant_lines[0][0]
        end_row = constant_lines[-1][0]
        text = "".join(const_text for _, const_text in constant_lines)

        return FileSnippet(file_path=file_path, start_row=start_row, end_row=end_row, text=text)

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

    This helps MyPy fixes that require cross-file understanding.
    """
    raise NotImplementedError
