# scripts/test_ruff_parse.py

import json
from pathlib import Path

from signals.parsers.ruff import parse_ruff_lint_results

def main() -> None:
    # Path to your Ruff JSON
    ruff_json_path = Path("/home/devel/cicd-ai-assistant/sample-cicd-artifacts/ruff-lint-results.json")

    # Load full JSON
    with ruff_json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Take only the first Ruff violation
    first_violation = data[0:1]

    # Parse into FixSignal list
    signals = parse_ruff_lint_results(
        first_violation,
        repo_root="/home/runner/work/ardessa-agent/ardessa-agent",
    )

    # Print results
    print(f"Parsed {len(signals)} FixSignal(s)\n")
    for s in signals:
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
