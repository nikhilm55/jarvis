"""Helper to clean git environment variables from subprocesses.

Git exports GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_PREFIX, etc. to hooks
and can interfere with subprocess git calls if inherited. This module provides
a utility to create a clean environment for git operations in tests.
"""

from __future__ import annotations

import os


def clean_git_env() -> dict[str, str]:
    """Return a copy of os.environ with all GIT_* variables removed.

    This prevents git environment variables set by the outer git process
    from interfering with subprocess git calls in tests.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
