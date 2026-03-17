"""Git branch management for the autoresearch loop.

Every function shells out to ``git`` via :mod:`subprocess` so the module has
no dependency on any Git library.  Functions accept an optional *repo_root*;
when omitted, the repo root is auto-detected from this file's location.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo-root detection
# ---------------------------------------------------------------------------

def _find_repo_root(start: str | None = None) -> str:
    """Walk up from *start* (default: this file's dir) until a ``.git``
    directory is found.  Falls back to cwd."""
    origin = Path(start) if start else Path(__file__).resolve().parent
    for p in (origin, *origin.parents):
        if (p / ".git").exists():
            return str(p)
    return os.getcwd()


_REPO_ROOT: str | None = None


def _root(repo_root: str | None = None) -> str:
    global _REPO_ROOT
    if repo_root:
        return repo_root
    if _REPO_ROOT is None:
        _REPO_ROOT = _find_repo_root()
    return _REPO_ROOT


# ---------------------------------------------------------------------------
# Low-level helper
# ---------------------------------------------------------------------------

def _git(*args: str, repo_root: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the completed process."""
    cmd = ["git"] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=_root(repo_root),
        check=check,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_branch(branch_name: str, repo_root: str | None = None) -> bool:
    """Create and checkout a new branch.

    Returns ``True`` if the branch was newly created, ``False`` if it
    already existed (in which case we just check it out).
    """
    # Check if branch already exists (local)
    result = _git("rev-parse", "--verify", branch_name, repo_root=repo_root, check=False)
    if result.returncode == 0:
        # Already exists — just switch to it
        _git("checkout", branch_name, repo_root=repo_root)
        return False
    # Create new branch and switch
    _git("checkout", "-b", branch_name, repo_root=repo_root)
    return True


def get_current_commit(repo_root: str | None = None) -> str:
    """Return the current HEAD commit hash (short, 8 chars)."""
    result = _git("rev-parse", "--short=8", "HEAD", repo_root=repo_root)
    return result.stdout.strip()


def commit_changes(
    message: str,
    paths: list[str] | None = None,
    repo_root: str | None = None,
) -> str:
    """Stage *paths* (or all tracked changes) and commit.

    Returns the new commit hash (short).
    """
    if paths:
        _git("add", "--", *paths, repo_root=repo_root)
    else:
        _git("add", "-A", repo_root=repo_root)

    _git("commit", "-m", message, repo_root=repo_root)
    return get_current_commit(repo_root=repo_root)


def revert_to_commit(commit_hash: str, repo_root: str | None = None) -> bool:
    """Hard-reset HEAD to *commit_hash*.

    Returns ``True`` on success, ``False`` on failure.
    """
    result = _git("reset", "--hard", commit_hash, repo_root=repo_root, check=False)
    return result.returncode == 0


def get_branch_name(repo_root: str | None = None) -> str:
    """Return the current branch name (e.g. ``main``)."""
    result = _git("rev-parse", "--abbrev-ref", "HEAD", repo_root=repo_root)
    return result.stdout.strip()


def ensure_autoresearch_branch(
    experiment_id: str,
    repo_root: str | None = None,
) -> str:
    """Create or checkout the ``autoresearch/{experiment_id}`` branch.

    If it already exists, we check it out.  If not, we create it from
    the current HEAD.  Returns the full branch name.
    """
    branch = f"autoresearch/{experiment_id}"
    create_branch(branch, repo_root=repo_root)
    return branch


def push_branch(
    branch_name: str | None = None,
    repo_root: str | None = None,
) -> bool:
    """Push the current (or named) branch to ``origin``.

    Returns ``True`` on success.
    """
    branch = branch_name or get_branch_name(repo_root=repo_root)
    result = _git(
        "push", "-u", "origin", branch,
        repo_root=repo_root,
        check=False,
    )
    return result.returncode == 0


def has_uncommitted_changes(repo_root: str | None = None) -> bool:
    """Return ``True`` if the working tree has uncommitted changes."""
    result = _git("status", "--porcelain", repo_root=repo_root)
    return bool(result.stdout.strip())


def get_diff_stat(commit_a: str, commit_b: str = "HEAD", repo_root: str | None = None) -> str:
    """Return a ``--stat`` diff between two commits."""
    result = _git("diff", "--stat", commit_a, commit_b, repo_root=repo_root, check=False)
    return result.stdout.strip()
