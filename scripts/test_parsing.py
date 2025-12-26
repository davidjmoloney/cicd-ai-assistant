# scripts/test_ruff_parse.py

import json
from pathlib import Path

from signals.parsers.ruff import parse_ruff_lint_results
from orchestrator.prioritizer import Prioritizer

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

    # Print results
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

if __name__ == "__main__":
    main()
