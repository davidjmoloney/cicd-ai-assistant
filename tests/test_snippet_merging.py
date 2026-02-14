"""Tests for overlapping edit snippet merging in ContextBuilder and AgentHandler."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from orchestrator.context_builder import ContextBuilder, EditSnippet, MergedSnippetGroup
from agents.agent_handler import AgentHandler, CodeEdit, EditType, FixPlan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_edit_snippet_dict(
    file_path: str,
    start_row: int,
    end_row: int,
    error_line: int,
    text: str = "placeholder",
) -> dict:
    """Create an edit snippet dict matching the structure used in context items."""
    return {
        "file_path": file_path,
        "start_row": start_row,
        "end_row": end_row,
        "text": text,
        "original_text": text,
        "error_line": error_line,
        "error_line_in_snippet": error_line - start_row + 1,
        "snippet_length": end_row - start_row + 1,
        "base_indent": "",
    }


def _make_signal_dict(file_path: str, row: int, column: int, message: str, rule_code: str = "arg-type") -> dict:
    """Create a signal metadata dict."""
    return {
        "tool_id": "mypy",
        "signal_type": "type_check",
        "severity": "high",
        "rule_code": rule_code,
        "message": message,
        "docs_url": None,
        "file_path": file_path,
        "span": {
            "start": {"row": row, "column": column},
            "end": {"row": row, "column": column},
        },
    }


def _make_context_item(file_path: str, row: int, column: int, message: str, snippet_start: int, snippet_end: int) -> dict:
    """Create a full context item (one entry in the 'signals' list)."""
    return {
        "signal": _make_signal_dict(file_path, row, column, message),
        "edit_snippet": _make_edit_snippet_dict(file_path, snippet_start, snippet_end, row),
        "code_context": {},
        "edit_window_type": "lines",
        "fix_context": {"exists": False},
        "file_read_error": None,
    }


# ---------------------------------------------------------------------------
# ContextBuilder._merge_overlapping_snippets tests
# ---------------------------------------------------------------------------

class TestMergeOverlappingSnippets:
    """Tests for the snippet merge logic on the ContextBuilder."""

    def _make_builder(self, file_contents: dict[str, str] | None = None):
        """Create a ContextBuilder with a mocked GitHub client and pre-populated file cache."""
        builder = ContextBuilder.__new__(ContextBuilder)
        builder._file_cache = {}
        builder._window_lines = 30
        builder._snippet_window_lines = 3
        builder._max_file_bytes = 512_000
        # Pre-populate file cache so _build_merged_group doesn't hit GitHub
        if file_contents:
            for fp, content in file_contents.items():
                lines = content.splitlines(keepends=True)
                builder._file_cache[fp] = (content, lines, None)
        return builder

    @staticmethod
    def _fake_file(num_lines: int = 100) -> str:
        """Generate a fake Python file with the given number of lines."""
        return "".join(f"line_{i}\n" for i in range(1, num_lines + 1))

    def test_overlapping_snippets_merge(self):
        """Two signals on the same line with overlapping edit windows → one merged group."""
        fake = self._fake_file(100)
        builder = self._make_builder({"clerk.py": fake})

        items = [
            _make_context_item("clerk.py", 81, 34, "arg jwks_url incompatible", 74, 88),
            _make_context_item("clerk.py", 81, 51, "arg issuer incompatible", 74, 88),
        ]

        merged, standalone = builder._merge_overlapping_snippets(items)

        assert len(merged) == 1
        assert merged[0].signal_indices == [0, 1]
        assert standalone == []
        # Merged snippet should cover the union range
        assert merged[0].edit_snippet.start_row == 74
        assert merged[0].edit_snippet.end_row == 88

    def test_adjacent_snippets_merge(self):
        """Snippets within gap ≤ 2 lines should merge."""
        fake = self._fake_file(30)
        builder = self._make_builder({"foo.py": fake})

        items = [
            _make_context_item("foo.py", 10, 1, "error A", 7, 13),
            _make_context_item("foo.py", 17, 1, "error B", 14, 20),  # gap = 14-13 = 1 ≤ 2
        ]

        merged, standalone = builder._merge_overlapping_snippets(items)

        assert len(merged) == 1
        assert merged[0].signal_indices == [0, 1]
        assert standalone == []
        # Union range: min(7,14)=7, max(13,20)=20
        assert merged[0].edit_snippet.start_row == 7
        assert merged[0].edit_snippet.end_row == 20

    def test_non_overlapping_same_file(self):
        """Snippets far apart in the same file should NOT merge."""
        builder = self._make_builder()

        items = [
            _make_context_item("foo.py", 10, 1, "error A", 7, 13),
            _make_context_item("foo.py", 50, 1, "error B", 47, 53),  # gap = 47-13 = 34 > 2
        ]

        merged, standalone = builder._merge_overlapping_snippets(items)

        assert len(merged) == 0
        assert sorted(standalone) == [0, 1]

    def test_different_files_no_merge(self):
        """Signals in different files should never merge."""
        builder = self._make_builder()

        items = [
            _make_context_item("a.py", 10, 1, "error A", 7, 13),
            _make_context_item("b.py", 10, 1, "error B", 7, 13),
        ]

        merged, standalone = builder._merge_overlapping_snippets(items)

        assert len(merged) == 0
        assert sorted(standalone) == [0, 1]

    def test_three_signals_chain_merge(self):
        """Three consecutive overlapping signals merge into one group."""
        fake = self._fake_file(30)
        builder = self._make_builder({"foo.py": fake})

        items = [
            _make_context_item("foo.py", 10, 1, "error A", 7, 13),
            _make_context_item("foo.py", 14, 1, "error B", 11, 17),
            _make_context_item("foo.py", 18, 1, "error C", 15, 21),
        ]

        merged, standalone = builder._merge_overlapping_snippets(items)

        assert len(merged) == 1
        assert merged[0].signal_indices == [0, 1, 2]
        assert standalone == []
        # Union range: 7 to 21
        assert merged[0].edit_snippet.start_row == 7
        assert merged[0].edit_snippet.end_row == 21

    def test_mixed_merged_and_standalone(self):
        """Some signals merge, others remain standalone."""
        fake = self._fake_file(60)
        builder = self._make_builder({"foo.py": fake, "bar.py": fake})

        items = [
            _make_context_item("foo.py", 10, 1, "error A", 7, 13),
            _make_context_item("foo.py", 12, 1, "error B", 9, 15),  # overlaps with 0
            _make_context_item("foo.py", 50, 1, "error C", 47, 53),  # standalone
            _make_context_item("bar.py", 5, 1, "error D", 2, 8),     # different file, standalone
        ]

        merged, standalone = builder._merge_overlapping_snippets(items)

        assert len(merged) == 1
        assert merged[0].signal_indices == [0, 1]
        assert sorted(standalone) == [2, 3]

    def test_no_edit_snippet_skipped(self):
        """Signals without edit snippets are treated as standalone."""
        builder = self._make_builder()

        items = [
            _make_context_item("foo.py", 10, 1, "error A", 7, 13),
            {
                "signal": _make_signal_dict("foo.py", 12, 1, "error B"),
                "edit_snippet": None,
                "code_context": {},
                "edit_window_type": "lines",
                "fix_context": {"exists": False},
                "file_read_error": "could not read",
            },
        ]

        merged, standalone = builder._merge_overlapping_snippets(items)

        assert len(merged) == 0
        assert sorted(standalone) == [0, 1]


# ---------------------------------------------------------------------------
# AgentHandler prompt building tests
# ---------------------------------------------------------------------------

class TestBuildUserPromptMerged:
    """Tests for _build_user_prompt with merged snippet groups."""

    def _make_handler(self):
        """Create an AgentHandler with a dummy provider."""
        from unittest.mock import MagicMock
        provider = MagicMock()
        provider.is_configured.return_value = True
        return AgentHandler(provider=provider)

    def test_merged_signals_produce_shared_block(self):
        """Merged signals should produce a single prompt block with 'shared edit region'."""
        handler = self._make_handler()

        context = {
            "group": {"tool_id": "mypy", "signal_type": "type_check", "group_size": 2},
            "signals": [
                _make_context_item("clerk.py", 81, 34, "arg jwks_url incompatible", 74, 88),
                _make_context_item("clerk.py", 81, 51, "arg issuer incompatible", 74, 88),
            ],
            "merged_snippet_groups": [
                {
                    "signal_indices": [0, 1],
                    "edit_snippet": _make_edit_snippet_dict("clerk.py", 74, 88, 81),
                }
            ],
            "standalone_signal_indices": [],
        }

        prompt = handler._build_user_prompt(context)

        # Should contain merged block header
        assert "shared edit region" in prompt
        assert "Error 1" in prompt
        assert "Error 2" in prompt
        assert "FIX ALL ERRORS ABOVE AND RETURN THIS" in prompt
        # Should NOT contain separate SIGNAL 1 / SIGNAL 2 blocks
        assert prompt.count("SIGNAL") == 0 or "SIGNALS" in prompt

    def test_standalone_signals_unchanged(self):
        """Standalone signals should produce individual blocks like before."""
        handler = self._make_handler()

        context = {
            "group": {"tool_id": "mypy", "signal_type": "type_check", "group_size": 2},
            "signals": [
                _make_context_item("a.py", 10, 1, "error A", 7, 13),
                _make_context_item("b.py", 20, 1, "error B", 17, 23),
            ],
            "merged_snippet_groups": [],
            "standalone_signal_indices": [0, 1],
        }

        prompt = handler._build_user_prompt(context)

        assert "SIGNAL 1" in prompt
        assert "SIGNAL 2" in prompt
        assert "shared edit region" not in prompt

    def test_backward_compat_no_merge_fields(self):
        """Context without merged_snippet_groups should still work (backward compat)."""
        handler = self._make_handler()

        context = {
            "group": {"tool_id": "mypy", "signal_type": "type_check", "group_size": 1},
            "signals": [
                _make_context_item("a.py", 10, 1, "error A", 7, 13),
            ],
        }

        prompt = handler._build_user_prompt(context)

        assert "SIGNAL 1" in prompt
        assert "FIX AND RETURN THIS" in prompt


# ---------------------------------------------------------------------------
# AgentHandler _parse_response tests with merged groups
# ---------------------------------------------------------------------------

class TestParseResponseMerged:
    """Tests for _parse_response handling merged groups."""

    def _make_handler(self):
        from unittest.mock import MagicMock
        provider = MagicMock()
        return AgentHandler(provider=provider)

    def test_merged_group_produces_one_edit(self):
        """A merged group should produce one CodeEdit with the merged snippet's span."""
        handler = self._make_handler()

        merged_snippet = _make_edit_snippet_dict("clerk.py", 74, 88, 81)

        context = {
            "group": {"tool_id": "mypy", "signal_type": "type_check", "group_size": 2},
            "signals": [
                _make_context_item("clerk.py", 81, 34, "arg jwks_url incompatible", 74, 88),
                _make_context_item("clerk.py", 81, 51, "arg issuer incompatible", 74, 88),
            ],
            "merged_snippet_groups": [
                {
                    "signal_indices": [0, 1],
                    "edit_snippet": merged_snippet,
                }
            ],
            "standalone_signal_indices": [],
        }

        # Simulate LLM returning one fix block (for the merged group)
        llm_content = (
            "===== FIX FOR: clerk.py =====\n"
            "CONFIDENCE: 0.9\n"
            "REASONING: Fixed both arg-type errors\n"
            "```FIXED_CODE\n"
            "fixed code here\n"
            "```\n"
            "WARNINGS: None\n"
            "===== END FIX =====\n"
        )

        plan = handler._parse_response(llm_content, context)

        assert len(plan.file_edits) == 1
        fe = plan.file_edits[0]
        assert fe.file_path == "clerk.py"
        assert len(fe.edits) == 1
        edit = fe.edits[0]
        # Should use the merged snippet span (74-88), not individual signal spans
        assert edit.span.start.row == 74
        assert edit.span.end.row == 88

    def test_mixed_merged_and_standalone_parse(self):
        """Response with one merged block + one standalone should parse correctly."""
        handler = self._make_handler()

        context = {
            "group": {"tool_id": "mypy", "signal_type": "type_check", "group_size": 3},
            "signals": [
                _make_context_item("clerk.py", 81, 34, "error A", 74, 88),
                _make_context_item("clerk.py", 81, 51, "error B", 74, 88),
                _make_context_item("other.py", 10, 1, "error C", 7, 13),
            ],
            "merged_snippet_groups": [
                {
                    "signal_indices": [0, 1],
                    "edit_snippet": _make_edit_snippet_dict("clerk.py", 74, 88, 81),
                }
            ],
            "standalone_signal_indices": [2],
        }

        llm_content = (
            "===== FIX FOR: clerk.py =====\n"
            "CONFIDENCE: 0.9\n"
            "REASONING: Fixed merged errors\n"
            "```FIXED_CODE\n"
            "merged fix\n"
            "```\n"
            "WARNINGS: None\n"
            "===== END FIX =====\n"
            "\n"
            "===== FIX FOR: other.py =====\n"
            "CONFIDENCE: 0.8\n"
            "REASONING: Fixed standalone error\n"
            "```FIXED_CODE\n"
            "standalone fix\n"
            "```\n"
            "WARNINGS: None\n"
            "===== END FIX =====\n"
        )

        plan = handler._parse_response(llm_content, context)

        assert len(plan.file_edits) == 2
        # First: merged clerk.py (span 74-88)
        assert plan.file_edits[0].file_path == "clerk.py"
        assert plan.file_edits[0].edits[0].span.start.row == 74
        assert plan.file_edits[0].edits[0].span.end.row == 88
        # Second: standalone other.py (span 7-13)
        assert plan.file_edits[1].file_path == "other.py"
        assert plan.file_edits[1].edits[0].span.start.row == 7
        assert plan.file_edits[1].edits[0].span.end.row == 13


# ---------------------------------------------------------------------------
# AgentHandler _build_response_index_map tests
# ---------------------------------------------------------------------------

class TestBuildResponseIndexMap:
    """Tests for the response index mapping logic."""

    def _make_handler(self):
        from unittest.mock import MagicMock
        provider = MagicMock()
        return AgentHandler(provider=provider)

    def test_all_standalone(self):
        """No merged groups → one entry per signal."""
        handler = self._make_handler()
        context = {
            "signals": [
                _make_context_item("a.py", 10, 1, "err", 7, 13),
                _make_context_item("b.py", 20, 1, "err", 17, 23),
            ],
            "merged_snippet_groups": [],
            "standalone_signal_indices": [0, 1],
        }

        rmap = handler._build_response_index_map(context)
        assert len(rmap) == 2
        assert rmap[0]["signal_indices"] == [0]
        assert rmap[1]["signal_indices"] == [1]

    def test_one_merged_group(self):
        """One merged group of 2 signals → one entry."""
        handler = self._make_handler()
        merged_snippet = _make_edit_snippet_dict("foo.py", 7, 20, 10)

        context = {
            "signals": [
                _make_context_item("foo.py", 10, 1, "err A", 7, 13),
                _make_context_item("foo.py", 14, 1, "err B", 11, 17),
            ],
            "merged_snippet_groups": [
                {"signal_indices": [0, 1], "edit_snippet": merged_snippet},
            ],
            "standalone_signal_indices": [],
        }

        rmap = handler._build_response_index_map(context)
        assert len(rmap) == 1
        assert rmap[0]["signal_indices"] == [0, 1]
        assert rmap[0]["edit_snippet"]["start_row"] == 7
        assert rmap[0]["edit_snippet"]["end_row"] == 20

    def test_backward_compat_no_merge_fields(self):
        """Missing merge fields → all signals treated as standalone."""
        handler = self._make_handler()
        context = {
            "signals": [
                _make_context_item("a.py", 10, 1, "err", 7, 13),
            ],
        }

        rmap = handler._build_response_index_map(context)
        assert len(rmap) == 1
        assert rmap[0]["signal_indices"] == [0]
