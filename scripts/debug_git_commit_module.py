
import httpx
import os
import json
from pathlib import Path
from datetime import datetime, timezone
from github.pr_generator import _github_headers, _github_request, PRGenerator
from agents.agent_handler import FixPlan
from dotenv import load_dotenv


# Load environment variables
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
TARGET_REPO_OWNER = os.getenv("TARGET_REPO_OWNER", "").strip()
TARGET_REPO_NAME = os.getenv("TARGET_REPO_NAME", "").strip()
TARGET_REPO_DEFAULT_BRANCH = "main"
PR_BRANCH_PREFIX = os.getenv("PR_BRANCH_PREFIX", "cicd-agent-fix").strip()
PR_LABELS = [l.strip() for l in os.getenv("PR_LABELS", "cicd-agent-generated").split(",") if l.strip()]
PR_DRAFT_MODE = os.getenv("PR_DRAFT_MODE", "false").lower() in ("true", "1", "yes")

# API constants
GITHUB_API_URL = "https://api.github.com"
MAX_RETRIES = 4
RETRY_DELAYS = [2, 4, 8, 16]

base = TARGET_REPO_DEFAULT_BRANCH
owner = TARGET_REPO_OWNER
repo = TARGET_REPO_NAME



DEBUG_FILE_EDITS = Path(__file__).parent / "commit_debug_file_edits.json"

with open(DEBUG_FILE_EDITS) as f:
    generated_fix_plan = FixPlan.from_dict(json.load(f))

pr_generator = PRGenerator() 

with httpx.Client(headers=_github_headers(), timeout=30.0) as client:
    # 1. Get base branch SHA
    ref_data = _github_request(client, "GET", f"/repos/{owner}/{repo}/git/ref/heads/{base}")
    base_sha = ref_data["object"]["sha"]

    # 2. Create new branch
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch_name = f"cicd-agent-fix/debug-commit-{timestamp}"
    _github_request(client, "POST", f"/repos/{owner}/{repo}/git/refs", {
        "ref": f"refs/heads/{branch_name}",
        "sha": base_sha,
    })

    # 3. Group edits by file (to handle multiple FileEdits for same file)
    merged_file_edits = pr_generator._merge_file_edits(generated_fix_plan.file_edits)

    # 4. Apply edits and commit each unique file
    files_changed: list[str] = []
    for file_edit in merged_file_edits:
        if pr_generator._commit_file_edit(client, owner, repo, file_edit, branch_name, base):
            files_changed.append(file_edit.file_path)
