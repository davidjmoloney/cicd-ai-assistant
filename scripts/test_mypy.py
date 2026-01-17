#!/usr/bin/env python3
"""
Parse a Ruff --diff (format) output file into FixSignals and write a readable TXT dump.

Run from your repo root (so imports resolve), e.g.:
  python tools/dump_ruff_format_signals_txt.py \
    --in ruff-format-output-short.txt \
    --out ruff-format-signals.txt
"""

from __future__ import annotations

import argparse
import pprint
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any
import json

from signals.models import FixSignal, SignalType
from orchestrator.prioritizer import Prioritizer, SignalGroup
from orchestrator.fix_planner import FixPlanner
from signals.parsers.ruff import parse_ruff_format_diff 
from github.pr_generator import PRGenerator
from agents.agent_handler import FixPlan


# Path to your Ruff format txt
ruff_json_path = Path("/home/devel/cicd-ai-assistant/sample-cicd-artifacts/ruff-format-cicd-short.txt")

# Output file paths
output_dir = Path(__file__).parent / "test-outputs"
context_output = output_dir / "ruff-format-fix-signals.txt"
fix_planner_output = output_dir / "ruff-format-fix-plan.json"

# Test Settings
OUTPUT_RUFF_FIX_SIGNALS=False
CREATE_RUFF_FIXPLANS=True
OUTPUT_RUFF_FIXPLANS=True
CREATE_RUFF_PR=True

def _to_plain(obj: Any) -> Any:
    """Convert dataclasses/enums/paths to plain Python types for pretty-printing."""
    if is_dataclass(obj):
        return {k: _to_plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


def main() -> int:

    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default=ruff_json_path)
    ap.add_argument("--out", dest="out_path", default=context_output)
    ap.add_argument(
        "--group-by-file",
        action="store_true",
        default=True,
        help="Group hunks into one FixSignal per file (default: true)",
    )
    ap.add_argument(
        "--no-group-by-file",
        dest="group_by_file",
        action="store_false",
        help="Emit one FixSignal per hunk instead",
    )
    args = ap.parse_args()

    diff_text = Path(args.in_path).read_text(encoding="utf-8")
    signals = parse_ruff_format_diff(diff_text, group_by_file=args.group_by_file)

    if OUTPUT_RUFF_FIX_SIGNALS:
        out_lines: list[str] = []
        out_lines.append(f"input_file: {args.in_path}")
        out_lines.append(f"group_by_file: {args.group_by_file}")
        out_lines.append(f"count: {len(signals)}")
        out_lines.append("")

        for i, s in enumerate(signals, start=1):
            out_lines.append(f"=== FixSignal {i}/{len(signals)} ===")
            out_lines.append(pprint.pformat(_to_plain(s), width=120, sort_dicts=False))
            out_lines.append("")

        Path(args.out_path).write_text("\n".join(out_lines), encoding="utf-8")
        print(f"Wrote {len(signals)} FixSignals to {args.out_path}")
    
    if  CREATE_RUFF_FIXPLANS:
        # Use prioritize to create SignalGroups
        prioritizer = Prioritizer()
        signal_groups = prioritizer.prioritize(signals=signals)

        fix_plans_for_pr_gen: list[FixPlan] = []
        planner = FixPlanner()

        for i, group in enumerate(signal_groups):

            plan_result = planner.create_fix_plan(group)
            fix_plans_for_pr_gen.append(plan_result.fix_plan)

            if OUTPUT_RUFF_FIXPLANS:
                print("\n--- Writing Ruff Fix Plan to JSON ---")
                with (fix_planner_output).open("a", encoding="utf-8") as f:
                    json.dump(plan_result.fix_plan.to_dict(), f, indent=2, default=str)


    if CREATE_RUFF_PR:
        # result.fix_plan is ready for PRGenerator
        pr_generator = PRGenerator()
        for plan in fix_plans_for_pr_gen:
            pr_result = pr_generator.create_pr(plan)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
