# signals/policy/path.py
from __future__ import annotations

from pathlib import Path


def to_repo_relative(path: str, repo_root: str | Path | None) -> str:
    """
    Convert absolute CI paths to repo-relative paths when possible.

    v1 policy:
    - If repo_root is provided and `path` is under it -> return relative path.
    - Otherwise return the original (normalized) path with leading slash stripped.

    This avoids the brittle "guess where app/src is" behaviour and ensures
    paths are always relative (required by GitHub API).
    """
    p = Path(path)
    if repo_root is None:
        # Strip leading slash to ensure relative path
        path_str = str(p)
        return path_str.lstrip('/')

    root = Path(repo_root)
    try:
        return str(p.relative_to(root))     # relative_to returns an exception ValueError if fails to deduce relative path
    except ValueError:
        # Strip leading slash to ensure relative path
        path_str = str(p)
        return path_str.lstrip('/')
