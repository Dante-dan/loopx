"""Owned physical roots for current and historical CLI output probes."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePath
import shutil
import tempfile


def budget_fixture_path(root: Path) -> Path:
    suffix = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    if os.name == "nt":
        # Keep the native name short without depending on a drive-root /tmp.
        return Path(tempfile.gettempdir()) / f"lxb-{suffix}"
    return Path("/tmp") / f"loopx-cli-budget-{suffix}"


@contextlib.contextmanager
def stable_budget_fixture_root(root: Path):
    fixture = budget_fixture_path(root)
    if fixture.exists() or fixture.is_symlink():
        raise RuntimeError(f"refusing to replace existing fixture root: {fixture}")
    fixture.mkdir()
    try:
        yield fixture
    finally:
        shutil.rmtree(fixture)


def long_path_budget_prefix(parent: PurePath) -> str:
    """Pad an owned root to 128 JSON string-content characters, not host path characters."""
    prefix = "loopx-brief-"
    # tempfile adds eight ASCII characters. Count JSON escaping of native
    # separators too: a deeper Windows namespace must not enlarge the workload.
    padding = 128 - (len(json.dumps(str(parent / prefix), ensure_ascii=False)) - 2) - 8
    if padding < 0:
        raise ValueError("temporary parent exceeds the serialized path workload")
    return prefix + "p" * padding
