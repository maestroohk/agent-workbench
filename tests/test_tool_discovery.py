"""Tests for the bootstrap dependency table and tool discovery.

Run with `python -m pytest tests/test_tool_discovery.py -v`. If pytest
is not installed: `pip install -r requirements-dev.txt`.

These tests cover the parts of `bootstrap.py` that the refactor
changed: the `role` key on every entry, the slimmed
`DEFAULT_BOOTSTRAP_SET`, and the `presence_hint` fallback for tools
that have a non-binary install footprint (notably firstmate, which
is a directory of `bin/fm-*.sh` scripts + an AGENTS.md manual).
"""
from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

import pytest


_HERE = Path(__file__).resolve().parent
_PYTHON_SRC = _HERE.parent / "scripts" / "python"
if str(_PYTHON_SRC) not in sys.path:
    sys.path.insert(0, str(_PYTHON_SRC))


def _import_bootstrap():
    """Import `bootstrap` fresh (it's a stateful module)."""
    if "bootstrap" in sys.modules:
        del sys.modules["bootstrap"]
    return importlib.import_module("bootstrap")


class TestRoleTaxonomy:
    """Every DEPENDENCIES entry must have a role key."""

    def test_every_entry_has_a_role(self) -> None:
        bootstrap = _import_bootstrap()
        missing = [name for name, entry in bootstrap.DEPENDENCIES.items() if "role" not in entry]
        assert not missing, f"DEPENDENCIES entries missing 'role' key: {missing}"

    def test_role_values_are_known(self) -> None:
        bootstrap = _import_bootstrap()
        known = {
            "orchestrator",
            "visual-collaboration",
            "isolation-manager",
            "validation-gate",
            "overnight-runner",
            "agent-runtime",
            "model-runtime",
            "terminal-fallback",
        }
        seen = {entry["role"] for entry in bootstrap.DEPENDENCIES.values()}
        unknown = seen - known
        assert not unknown, f"unknown role values: {unknown}"

    def test_specific_role_mappings(self) -> None:
        bootstrap = _import_bootstrap()
        # Spot-check the most-important role assignments.
        assert bootstrap.DEPENDENCIES["firstmate"]["role"] == "orchestrator"
        assert bootstrap.DEPENDENCIES["lavish-axi"]["role"] == "visual-collaboration"
        assert bootstrap.DEPENDENCIES["treehouse"]["role"] == "isolation-manager"
        assert bootstrap.DEPENDENCIES["no-mistakes"]["role"] == "validation-gate"
        assert bootstrap.DEPENDENCIES["gnhf"]["role"] == "overnight-runner"
        assert bootstrap.DEPENDENCIES["herdr"]["role"] == "agent-runtime"


class TestDefaultBootstrapSet:
    """`DEFAULT_BOOTSTRAP_SET` is the slim runtime set."""

    def test_treehouse_not_in_default(self) -> None:
        bootstrap = _import_bootstrap()
        assert "treehouse" not in bootstrap.DEFAULT_BOOTSTRAP_SET

    def test_default_has_core_three(self) -> None:
        bootstrap = _import_bootstrap()
        for required in ("herdr", "firstmate", "no-mistakes"):
            assert required in bootstrap.DEFAULT_BOOTSTRAP_SET, (
                f"{required} missing from DEFAULT_BOOTSTRAP_SET"
            )


class TestCheckDependencies:
    """`check_dependencies` should probe + honour presence_hint."""

    def test_present_via_presence_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bootstrap = _import_bootstrap()
        # Make `firstmate` look absent on PATH. The firstmate entry
        # has `presence_hint: "${HOME}/firstmate/AGENTS.md"`, so
        # creating that file under a fake HOME flips the result to
        # present.
        monkeypatch.setattr(shutil, "which", lambda name: None)
        fake_harness = tmp_path / "firstmate"
        fake_harness.mkdir()
        (fake_harness / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
        monkeypatch.setenv("HOME", str(tmp_path))

        statuses = bootstrap.check_dependencies(["firstmate"])
        assert len(statuses) == 1
        firstmate = statuses[0]
        assert firstmate.name == "firstmate"
        assert firstmate.present is True, (
            f"expected firstmate to be present via presence_hint; got {firstmate}"
        )

    def test_absent_without_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bootstrap = _import_bootstrap()
        monkeypatch.setattr(shutil, "which", lambda name: None)
        # No fake HOME; firstmate is genuinely absent.
        monkeypatch.delenv("HOME", raising=False)
        statuses = bootstrap.check_dependencies(["firstmate"])
        firstmate = next(s for s in statuses if s.name == "firstmate")
        # The presence_hint uses ${HOME} which os.path.expandvars
        # expands against the current environment. Either way, when
        # there's no harness the tool should be reported absent.
        assert firstmate.present is False

    def test_unknown_dep_reports_error(self) -> None:
        bootstrap = _import_bootstrap()
        statuses = bootstrap.check_dependencies(["not-a-real-dep-xyz"])
        assert len(statuses) == 1
        bogus = statuses[0]
        assert bogus.name == "not-a-real-dep-xyz"
        assert bogus.present is False
        assert bogus.error is not None
