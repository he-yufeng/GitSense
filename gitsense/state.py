"""Per-user state directory for watch history and triage snapshots.

State used to live in ``./.gitsense`` next to wherever the command ran, so
history silently reset the moment you ran gitsense from another folder. It
now defaults to ``~/.gitsense`` and ``--state-dir`` overrides that. On the
first run from a folder that still has a legacy ``./.gitsense`` file, the
file is copied into the new location (the original is left alone).
"""

from __future__ import annotations

import os
import shutil

_LEGACY_DIR = ".gitsense"


def state_dir(override: str | None = None) -> str:
    """The directory GitSense keeps its state in."""
    if override:
        return os.path.expanduser(override)
    return os.path.join(os.path.expanduser("~"), _LEGACY_DIR)


def resolve_state_file(override: str | None, filename: str) -> str:
    """Path of one state file, copying a legacy CWD-local copy over once."""
    root = state_dir(override)
    new_path = os.path.join(root, filename)
    if override is not None:
        return new_path
    legacy = os.path.join(".", _LEGACY_DIR, filename)
    if not os.path.exists(new_path) and os.path.exists(legacy):
        try:
            os.makedirs(root, exist_ok=True)
            shutil.copy2(legacy, new_path)
        except OSError:
            # home not writable: keep using the legacy file rather than lose it
            return legacy
    return new_path
