#!/usr/bin/env python3
"""
Parse MyPy JSON output into FixSignals and write a readable TXT dump.

Run from your repo root (so imports resolve), e.g.:
  python scripts/test_mypy.py
"""

from __future__ import annotations

import argparse
import pprint
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any
import json
import logging
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

# Enable LLM context debugging - dumps context to scripts/debug/llm-contexts/                                                                                                                                                
os.environ["DEBUG_LLM"] = "true"  

from signals.models import FixSignal, SignalType
from orchestrator.prioritizer import Prioritizer, SignalGroup
from orchestrator.fix_planner import FixPlanner
from signals.parsers.mypy import parse_mypy_results
from github.pr_generator import PRGenerator
from agents.agent_handler import FixPlan


# Path to your MyPy JSON output
mypy_json_path = Path("/home/devel/cicd-ai-assistant/sample-cicd-artifacts/mypy-results-short-debug.json")

# Output file paths
output_dir = Path(__file__).parent / "test-outputs"
context_output = output_dir / "mypy-fix-signals-debug.txt"
fix_planner_output = output_dir / "mypy-fix-plan.json"

# Test Settings
PARSE_MYPY_AND_OUTPUT=True
CREATE_PR_FROM_FIXPLAN=True

def main() -> int:
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if PARSE_MYPY_AND_OUTPUT:
        # Parse MyPy JSON output
        mypy_output = Path(mypy_json_path).read_text(encoding="utf-8")
        signals = parse_mypy_results(mypy_output, repo_root="/home/devel/cicd-ai-assistant/test-repo-stripped/")

        # Output fix signals to a file for inspection
        out_lines = [f"Parsed {len(signals)} MyPy FixSignals:\n"]

        for i, sig in enumerate(signals, start=1):
            out_lines.append(f"Signal #{i}")
            out_lines.append(f"  Type: {sig.signal_type}")
            out_lines.append(f"  Severity: {sig.severity}")
            out_lines.append(f"  File: {sig.file_path}")
            out_lines.append(f"  Location: line {sig.span.start.row}, column {sig.span.start.column}")
            out_lines.append(f"  Rule Code: {sig.rule_code}")
            out_lines.append(f"  Message: {sig.message}")
            if sig.docs_url:
                out_lines.append(f"  Docs: {sig.docs_url}")
            out_lines.append(f"  Fix: {sig.fix or 'None (requires LLM)'}")
            out_lines.append("")

        Path(context_output).write_text("\n".join(out_lines), encoding="utf-8")
        print(f"Wrote {len(signals)} FixSignals to {context_output}")

        # Use prioritize to create SignalGroups
        prioritizer = Prioritizer()
        signal_groups = prioritizer.prioritize(signals=signals)
        planner = FixPlanner(repo_root="/home/devel/cicd-ai-assistant/test-repo-stripped/")
        fix_plans_from_llm: list[FixPlan] = []

        for group in signal_groups:
            plan_result = planner.create_fix_plan(group)
            fix_plans_from_llm.append(plan_result.fix_plan)
        
        with (fix_planner_output).open("w", encoding="utf-8") as f:
            f.write("[")
            for i, plan in enumerate(fix_plans_from_llm):
                print(f"\n--- Writing MyPy Fix Plan {i} to JSON ---")
                json.dump(plan.to_dict(), f, indent=2, default=str)
                if i != (len(fix_plans_from_llm) - 1): 
                    f.write(",\n")
            f.write("]")


    if CREATE_PR_FROM_FIXPLAN:
        file_content: dict = []
        fix_plans_for_pr_gen: list[FixPlan] = []
        with open(fix_planner_output) as f:
            file_content = json.load(f)
        for dict_entry in file_content:
            fix_plan = FixPlan.from_dict(dict_entry)
            fix_plans_for_pr_gen.append(fix_plan)
 
        # result.fix_plan is ready for PRGenerator
        pr_generator = PRGenerator()
        for i, plan in enumerate(fix_plans_for_pr_gen, start = 1):    
            pr_result = pr_generator.create_pr(fix_plans_for_pr_gen[i-1])
            print(f"\n------ Results for PR {i} -------")
            print(f"PR Generation success: {pr_result.success}")
            print(f"PR URL: {pr_result.pr_url}")
            for file in pr_result.files_changed:
                print(f"   File changed {file}")
            print("\n\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
