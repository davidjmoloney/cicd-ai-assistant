# scripts/test_ruff_parse.py

import json
from pathlib import Path

from signals.parsers.ruff import parse_ruff_lint_results
from orchestrator.prioritizer import Prioritizer
from orchestrator.context_builder import ContextBuilder

def main() -> None:
    # Path to your Ruff JSON
    ruff_json_path = Path("/home/devel/cicd-ai-assistant/sample-cicd-artifacts/ruff-lint-results.json")

    # Output file paths
    output_dir = Path(__file__).parent
    summary_output = output_dir / "signal_summary.txt"
    context_output = output_dir / "context_output.json"

    # Load full JSON
    with ruff_json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Parse into FixSignal list
    signals = parse_ruff_lint_results(
        data,
        repo_root="/home/runner/work/ardessa-agent/ardessa-agent",
    )

    prioritizer = Prioritizer()
    groups = prioritizer.prioritize(signals)

    # Write signal summary to file
    with summary_output.open("w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("SIGNAL GROUP SUMMARY\n")
        f.write("=" * 80 + "\n")
        for s in groups[0].signals:
            f.write("---- FixSignal ----\n")
            f.write(f"Type:        {s.signal_type}\n")
            f.write(f"Severity:    {s.severity}\n")
            f.write(f"File:        {s.file_path}\n")
            f.write(f"Rule:        {s.rule_code}\n")
            f.write(f"Message:     {s.message}\n")
            f.write(f"Span:        {s.span}\n")

            if s.fix:
                f.write(f"Fix safe?:   {s.fix.applicability}\n")
                f.write(f"Fix message: {s.fix.message}\n")
                f.write(f"Edits:       {len(s.fix.edits)}\n")
            else:
                f.write("Fix:         None\n")

    print(f"✓ Signal summary written to: {summary_output}")

    # Build context using ContextBuilder
    context_builder = ContextBuilder(
        repo_root="/home/runner/work/ardessa-agent/ardessa-agent",
        window_lines=10,  # ±10 lines around each issue
    )

    # Build context for the first group and write to file
    if groups:
        context = context_builder.build_group_context(groups[0])

        # Write context as pretty-printed JSON
        with context_output.open("w", encoding="utf-8") as f:
            json.dump(context, f, indent=2, default=str)

        print(f"✓ Context output written to: {context_output}")
    else:
        print("✗ No signal groups to process")

if __name__ == "__main__":
    main()
