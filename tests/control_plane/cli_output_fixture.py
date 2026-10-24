"""Physical fixture lifecycle shared by current and historical CLI probes."""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path


def budget_fixture_parent() -> Path:
    # Retain the characterized POSIX paths. Native Windows has no /tmp contract.
    return Path(tempfile.gettempdir()) if os.name == "nt" else Path("/tmp")


@contextlib.contextmanager
def stable_budget_fixture_root(root: Path) -> Iterator[Path]:
    suffix = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    fixture = budget_fixture_parent() / f"loopx-cli-budget-{suffix}"
    if fixture.exists() or fixture.is_symlink():
        raise RuntimeError(f"refusing to replace existing fixture root: {fixture}")
    fixture.mkdir()
    try:
        yield fixture
    finally:
        shutil.rmtree(fixture)
