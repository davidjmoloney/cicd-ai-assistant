#!/usr/bin/env python3
"""
CI/CD AI Assistant — Main Entry Point.

Reads CI/CD tool artifacts from a directory, parses them into signals,
prioritises and groups them, generates fixes (direct or LLM-assisted),
and creates pull requests with the results.

Usage:
    python -m main                          # defaults: cicd-artifacts/
    python -m main --artifacts-dir ./my-artifacts

Configuration (environment variables):
    CONFIDENCE_THRESHOLD  - Min confidence to include a fix in PR (default: 0.7)
    SIGNALS_PER_PR        - Max signals per group sent to LLM     (default: 3)
    LLM_PROVIDER          - LLM provider name                     (default: "openai")
    LOG_LEVEL             - "info" (default) or "debug"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Optional dotenv support for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from signals.models import FixSignal, SignalType
from signals.parsers.mypy import parse_mypy_results
from signals.parsers.ruff import parse_ruff_lint_results, parse_ruff_format_diff
from signals.parsers.pydocstyle import parse_pydocstyle_results
from orchestrator.prioritizer import Prioritizer, SignalGroup
from orchestrator.fix_planner import FixPlanner, PlannerResult
from github.pr_generator import PRGenerator, PRResult


# =============================================================================
# Environment Variable Configuration
# =============================================================================

def _read_config() -> dict:
    """Read configuration from environment variables.

    Returns:
        Dict with keys: confidence_threshold, signals_per_pr, llm_provider,
        log_level.
    """
    return {
        "confidence_threshold": float(
            os.getenv("CONFIDENCE_THRESHOLD", "0.7")
        ),
        "signals_per_pr": int(
            os.getenv("SIGNALS_PER_PR", "3")
        ),
        "llm_provider": os.getenv("LLM_PROVIDER", "openai").strip(),
        "log_level": os.getenv("LOG_LEVEL", "info").strip().lower(),
        # ── placeholder: add future env vars here ──
    }


# =============================================================================
# Artifact Discovery & Parser Routing
# =============================================================================

def discover_artifacts(artifacts_dir: Path) -> list[Path]:
    """Return all regular files in *artifacts_dir*, sorted by name."""
    if not artifacts_dir.is_dir():
        raise FileNotFoundError(f"Artifacts directory not found: {artifacts_dir}")
    return sorted(p for p in artifacts_dir.iterdir() if p.is_file())


def _route_artifact(path: Path) -> Optional[str]:
    """Determine the parser type for an artifact file based on its name.

    Returns one of: "mypy", "ruff-lint", "ruff-format", "pydocstyle",
    or None if the file should be skipped.
    """
    name = path.name.lower()

    # ruff-format diff files (text only — the .json status file is skipped)
    if "ruff-format" in name or ("ruff" in name and "format" in name):
        if path.suffix == ".txt":
            return "ruff-format"
        return None  # skip the JSON status stub

    # ruff lint JSON results
    if "ruff" in name and "lint" in name:
        return "ruff-lint"

    # mypy JSON results
    if "mypy" in name or "my-py" in name:
        return "mypy"

    # pydocstyle text output
    if "pydocstyle" in name:
        return "pydocstyle"

    return None


def parse_artifact(path: Path, parser_type: str) -> list[FixSignal]:
    """Read *path* and run the appropriate parser.

    Returns a (possibly empty) list of FixSignal objects.
    """
    raw = path.read_text(encoding="utf-8")

    if parser_type == "mypy":
        return parse_mypy_results(raw)
    elif parser_type == "ruff-lint":
        return parse_ruff_lint_results(raw)
    elif parser_type == "ruff-format":
        return parse_ruff_format_diff(raw)
    elif parser_type == "pydocstyle":
        return parse_pydocstyle_results(raw)
    else:
        return []


# =============================================================================
# Run Metrics
# =============================================================================

@dataclass
class RunMetrics:
    """Collects metrics for a single assistant run."""
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None

    # Parsing
    artifacts_found: int = 0
    artifacts_parsed: int = 0
    total_signals: int = 0
    signals_by_type: dict[str, int] = field(default_factory=dict)

    # Fix planning
    signal_groups: int = 0
    fix_plans_created: int = 0
    fix_plans_failed: int = 0
    llm_calls: int = 0
    direct_fixes: int = 0

    # PR generation
    prs_created: int = 0
    prs_failed: int = 0
    signals_fixed: int = 0
    signals_fixed_by_type: dict[str, int] = field(default_factory=dict)
    signals_skipped: int = 0

    def finish(self) -> None:
        self.end_time = datetime.now(timezone.utc)

    @property
    def duration_seconds(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time).total_seconds()

    def record_signals(self, signals: list[FixSignal]) -> None:
        """Record parsed signal counts by type."""
        for sig in signals:
            key = sig.signal_type.value
            self.signals_by_type[key] = self.signals_by_type.get(key, 0) + 1
        self.total_signals += len(signals)

    def record_pr(self, pr_result: PRResult, group: SignalGroup) -> None:
        """Record a single PR result into the metrics."""
        if pr_result.success and pr_result.pr_url:
            self.prs_created += 1
            fixed_count = len(pr_result.files_changed)
            self.signals_fixed += fixed_count
            key = group.signal_type.value
            self.signals_fixed_by_type[key] = (
                self.signals_fixed_by_type.get(key, 0) + fixed_count
            )
        elif not pr_result.success:
            self.prs_failed += 1

        self.signals_skipped += len(pr_result.skipped_fixes)


def write_run_report(metrics: RunMetrics, output_dir: Path) -> Path:
    """Write an info-level run report to a timestamped file.

    Returns the path of the written report.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = metrics.start_time.strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"run_report_{ts}.txt"

    lines = [
        "=" * 60,
        "CI/CD AI Assistant — Run Report",
        "=" * 60,
        "",
        f"Start time : {metrics.start_time.isoformat()}",
        f"End time   : {metrics.end_time.isoformat() if metrics.end_time else 'N/A'}",
        f"Duration   : {metrics.duration_seconds:.1f}s",
        "",
        "── Parsing ──────────────────────────────────────────────",
        f"Artifacts found  : {metrics.artifacts_found}",
        f"Artifacts parsed : {metrics.artifacts_parsed}",
        f"Total signals    : {metrics.total_signals}",
    ]
    for stype, count in sorted(metrics.signals_by_type.items()):
        lines.append(f"  {stype:20s}: {count}")

    lines.extend([
        "",
        "── Fix Planning ─────────────────────────────────────────",
        f"Signal groups    : {metrics.signal_groups}",
        f"Fix plans OK     : {metrics.fix_plans_created}",
        f"Fix plans failed : {metrics.fix_plans_failed}",
        f"LLM calls        : {metrics.llm_calls}",
        f"Direct fixes     : {metrics.direct_fixes}",
        "",
        "── PR Generation ────────────────────────────────────────",
        f"PRs created      : {metrics.prs_created}",
        f"PRs failed       : {metrics.prs_failed}",
        f"Signals fixed    : {metrics.signals_fixed}",
    ])
    for stype, count in sorted(metrics.signals_fixed_by_type.items()):
        lines.append(f"  {stype:20s}: {count}")
    lines.append(f"Signals skipped  : {metrics.signals_skipped}")

    lines.extend(["", "=" * 60])

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


# =============================================================================
# Main Pipeline
# =============================================================================

def run(artifacts_dir: Path, config: dict) -> RunMetrics:
    """Execute the full pipeline: parse → prioritise → plan → PR.

    Args:
        artifacts_dir: Directory containing CI/CD tool output files.
        config: Configuration dict from _read_config().

    Returns:
        RunMetrics summarising the run.
    """
    metrics = RunMetrics()

    confidence_threshold: float = config["confidence_threshold"]
    signals_per_pr: int = config["signals_per_pr"]
    llm_provider: str = config["llm_provider"]
    log_level: str = config["log_level"]

    # ── 1. Discover & parse artifacts ──────────────────────────
    print(f"[main] Scanning artifacts in {artifacts_dir}")
    artifact_files = discover_artifacts(artifacts_dir)
    metrics.artifacts_found = len(artifact_files)

    all_signals: list[FixSignal] = []

    for path in artifact_files:
        parser_type = _route_artifact(path)
        if parser_type is None:
            print(f"[main]   skip {path.name} (no matching parser)")
            continue

        print(f"[main]   parsing {path.name} with {parser_type}")
        try:
            signals = parse_artifact(path, parser_type)
            all_signals.extend(signals)
            metrics.artifacts_parsed += 1
            print(f"[main]     → {len(signals)} signal(s)")
        except Exception as exc:
            print(f"[main]     ✗ parse error: {exc}")

    metrics.record_signals(all_signals)
    print(f"[main] Total signals parsed: {metrics.total_signals}")

    if not all_signals:
        print("[main] No signals found — nothing to do.")
        metrics.finish()
        return metrics

    # ── 2. Prioritise & group ──────────────────────────────────
    prioritizer = Prioritizer(max_group_size=signals_per_pr)
    groups = prioritizer.prioritize(all_signals)
    metrics.signal_groups = len(groups)
    print(f"[main] Signal groups: {len(groups)}")

    # ── 3. Generate fix plans ──────────────────────────────────
    planner = FixPlanner(llm_provider=llm_provider)
    pr_generator = PRGenerator(confidence_threshold=confidence_threshold)

    for idx, group in enumerate(groups, 1):
        label = f"[group {idx}/{len(groups)} | {group.tool_id} {group.signal_type.value}]"
        print(f"[main] {label} {len(group.signals)} signal(s)")

        planner_result: PlannerResult = planner.create_fix_plan(group)

        if planner_result.used_llm:
            metrics.llm_calls += 1
        else:
            metrics.direct_fixes += 1

        if not planner_result.success or planner_result.fix_plan is None:
            print(f"[main]   {label} fix plan failed: {planner_result.error}")
            metrics.fix_plans_failed += 1
            continue

        metrics.fix_plans_created += 1

        # ── 4. Create PR ──────────────────────────────────────
        pr_result: PRResult = pr_generator.create_pr(planner_result.fix_plan)
        metrics.record_pr(pr_result, group)

        if pr_result.success and pr_result.pr_url:
            print(f"[main]   {label} PR created: {pr_result.pr_url}")
        elif pr_result.success and not pr_result.pr_url:
            print(f"[main]   {label} all fixes below threshold — no PR")
        else:
            print(f"[main]   {label} PR failed: {pr_result.error}")

        if pr_result.skipped_fixes:
            print(
                f"[main]   {label} skipped {len(pr_result.skipped_fixes)} "
                "fix(es) below confidence threshold"
            )

    metrics.finish()
    return metrics


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CI/CD AI Assistant — parse signals, generate fixes, create PRs",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("cicd-artifacts"),
        help="Directory containing CI/CD tool output files (default: cicd-artifacts/)",
    )
    args = parser.parse_args()

    config = _read_config()
    print(f"[main] Config: threshold={config['confidence_threshold']}, "
          f"signals_per_pr={config['signals_per_pr']}, "
          f"provider={config['llm_provider']}, "
          f"log_level={config['log_level']}")

    metrics = run(args.artifacts_dir, config)

    # ── Write run report ───────────────────────────────────────
    report_dir = Path("logs")
    report_path = write_run_report(metrics, report_dir)
    print(f"\n[main] Run report written to {report_path}")

    # Print summary to stdout
    print(f"\n{'─' * 40}")
    print(f"Signals: {metrics.total_signals} parsed, "
          f"{metrics.signals_fixed} fixed, "
          f"{metrics.signals_skipped} skipped")
    print(f"PRs: {metrics.prs_created} created, "
          f"{metrics.prs_failed} failed")
    print(f"Duration: {metrics.duration_seconds:.1f}s")


if __name__ == "__main__":
    main()
