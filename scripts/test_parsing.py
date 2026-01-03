# scripts/test_ruff_parse.py

import json
from pathlib import Path

from signals.parsers.ruff import parse_ruff_lint_results
from orchestrator.prioritizer import Prioritizer
from orchestrator.context_builder import ContextBuilder

def main() -> None:
    # Path to your Ruff JSON
    ruff_json_path = Path("/home/devel/cicd-ai-assistant/sample-cicd-artifacts/ruff-lint-results.json")

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

    # Print results from first group
    print("=" * 80)
    print("SIGNAL GROUP SUMMARY")
    print("=" * 80)
    for s in groups[0].signals:
        print("---- FixSignal ----")
        print(f"Type:        {s.signal_type}")
        print(f"Severity:    {s.severity}")
        print(f"File:        {s.file_path}")
        print(f"Rule:        {s.rule_code}")
        print(f"Message:     {s.message}")
        print(f"Span:        {s.span}")

        if s.fix:
            print(f"Fix safe?:   {s.fix.applicability}")
            print(f"Fix message: {s.fix.message}")
            print(f"Edits:       {len(s.fix.edits)}")
        else:
            print("Fix:         None")

    # Build context using ContextBuilder
    print("\n" + "=" * 80)
    print("CONTEXT BUILDER OUTPUT")
    print("=" * 80)

    context_builder = ContextBuilder(
        repo_root="/home/runner/work/ardessa-agent/ardessa-agent",
        window_lines=10,  # ±10 lines around each issue
    )

    # Build context for the first group
    if groups:
        context = context_builder.build_group_context(groups[0])

        # Pretty-print the context as JSON
        print(json.dumps(context, indent=2, default=str))
    else:
        print("No signal groups to process")

if __name__ == "__main__":
    main()
