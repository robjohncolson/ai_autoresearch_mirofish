"""Autoresearch loop engine — metrics, git ops, inner runner, and outer
course progression.

Usage::

    from loop import (
        IterationMetrics, compute_metrics, is_improvement,
        create_branch, get_current_commit, commit_changes, revert_to_commit,
        AutoresearchRunner,
        CourseProgression,
    )
"""

from .metrics import IterationMetrics, compute_metrics, is_improvement
from .git_ops import (
    create_branch,
    get_current_commit,
    commit_changes,
    revert_to_commit,
    ensure_autoresearch_branch,
    push_branch,
    get_branch_name,
)
from .runner import AutoresearchRunner
from .progression import CourseProgression

__all__ = [
    # metrics
    "IterationMetrics",
    "compute_metrics",
    "is_improvement",
    # git_ops
    "create_branch",
    "get_current_commit",
    "commit_changes",
    "revert_to_commit",
    "ensure_autoresearch_branch",
    "push_branch",
    "get_branch_name",
    # runner
    "AutoresearchRunner",
    # progression
    "CourseProgression",
]
