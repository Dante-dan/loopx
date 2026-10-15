"""Incomplete directory enumeration must never certify a clean public boundary."""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path

import pytest

from loopx.contract import check_contract, scan_public_boundary
from loopx.control_plane.testing.canary_harness import run_json_cli_result


def _registry(tmp_path: Path) -> Path:
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema_version": 1, "common_runtime_root": str(tmp_path / "runtime"), "goals": []}), encoding="utf-8")
    return registry


@pytest.mark.parametrize("denied_name", [".", "notes", "notes/nested"])
def test_scan_fails_closed_on_directory_listing_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, denied_name: str,
) -> None:
    root = tmp_path / "tree"
    denied = root / denied_name
    denied.mkdir(parents=True)
    (root / "PUBLIC.md").write_text("public text\n", encoding="utf-8")
    (denied / "private.md").write_text("internal host " + "10." + "0.0.7\n", encoding="utf-8")
    original_scandir = os.scandir

    def deny_scandir(path):
        if Path(path) == denied:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", deny_scandir)
    boundary = scan_public_boundary([root])

    assert boundary["ok"] is False
    assert boundary["unreadable_directories"] == [f"{Path(denied_name)}: Permission denied"]
    assert boundary["scanned_files"] == (0 if denied == root else 1)
    assert boundary["hits"] == []


def test_contract_reports_directory_error_and_keeps_readable_sibling_hits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "tree"
    denied = root / "notes"
    denied.mkdir(parents=True)
    (root / "visible.md").write_text("internal host " + "10." + "0.0.7\n", encoding="utf-8")
    original_scandir = os.scandir

    def deny_scandir(path):
        if Path(path) == denied:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", deny_scandir)
    result = check_contract(
        registry_path=_registry(tmp_path), runtime_root_override=None,
        scan_roots=[root], limit=5,
    )

    assert result["ok"] is False
    assert result["public_boundary_scan"]["ok"] is False
    assert result["public_boundary_scan"]["unreadable_directories"] == [
        "notes: Permission denied"
    ]
    assert any(d["code"] == "public_boundary_directory_unreadable"
               and "notes: Permission denied" in d["message"]
               for d in result["error_diagnostics"])
    assert any(d["code"] == "public_boundary_violation"
               and "visible.md:1: private_ip" in d["message"]
               for d in result["error_diagnostics"])
    assert not any(c.startswith("public boundary scan clean") for c in result["checks"])


@pytest.mark.skipif(os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0,
                    reason="mode-000 directory denial requires non-root POSIX")
def test_check_cli_fails_on_real_unreadable_directory_and_recovers(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    denied = root / "notes"
    denied.mkdir(parents=True)
    (root / "PUBLIC.md").write_text("public text\n", encoding="utf-8")
    (denied / "private.md").write_text("internal host " + "10." + "0.0.7\n", encoding="utf-8")
    registry = _registry(tmp_path)
    denied.chmod(0o000)
    try:
        code, result = run_json_cli_result("check", "--scan-path", str(root), registry_path=registry)
    finally:
        denied.chmod(0o755)
    assert code == 1
    assert result["ok"] is False
    assert result["public_boundary_scan"]["unreadable_directories"]
    assert any("notes" in error for error in result["errors"])
    code, recovered = run_json_cli_result("check", "--scan-path", str(root), registry_path=registry)
    assert code == 1
    assert recovered["public_boundary_scan"]["unreadable_directories"] == []
    assert any("private.md:1: private_ip" in error for error in recovered["errors"])


def test_intentionally_pruned_dependency_directory_is_not_a_listing_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    denied = tmp_path / "node_modules"
    denied.mkdir()
    (tmp_path / "PUBLIC.md").write_text("public text\n", encoding="utf-8")
    original_scandir = os.scandir

    def deny_scandir(path):
        if Path(path) == denied:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", deny_scandir)
    boundary = scan_public_boundary([tmp_path])
    assert boundary["ok"] is True
    assert boundary["scanned_files"] == 1
    assert boundary["unreadable_directories"] == []
