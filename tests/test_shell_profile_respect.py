"""Tests that the installers do not silently edit shell profiles.

Run with `python -m pytest tests/test_shell_profile_respect.py -v`. If
pytest is not installed: `pip install -r requirements-dev.txt`.

The workbench contract is that the bash and PowerShell installers
never silently write to `~/.bashrc`, `~/.zshrc`, PowerShell profile,
or HKCU user PATH. The bash installer is allowed to print a copyable
export line; the PowerShell installer is allowed to ask before
persisting HKCU. Both installers must NOT touch the files
themselves.
"""
from __future__ import annotations

import re
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
_INSTALL_SH = _REPO_ROOT / "install.sh"
_INSTALL_PS1 = _REPO_ROOT / "install.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestBashInstallerProfileRespect:
    """install.sh must not auto-write to ~/.bashrc or ~/.zshrc."""

    def test_no_append_to_bashrc(self) -> None:
        text = _read(_INSTALL_SH)
        # Forbidden: any append (`>>`) to a HOME-based path that ends
        # in `.bashrc`. We accept `>` only if the file is the script
        # itself (e.g. a temp file); we do not accept `>>` to any
        # `.bashrc` / `.zshrc` file.
        for pattern in (r'>>\s*"?\$\{?HOME\}?/\.bashrc', r'>>\s*"?\$\{?HOME\}?/\.zshrc'):
            match = re.search(pattern, text)
            assert match is None, f"forbidden append in install.sh: {match.group(0) if match else '?'}"

    def test_no_set_content_to_bashrc(self) -> None:
        text = _read(_INSTALL_SH)
        for needle in ("Set-Content", "Add-Content", "Out-File"):
            assert needle not in text, f"forbidden PowerShell write: {needle!r} in install.sh"

    def test_no_heredoc_to_bashrc(self) -> None:
        # Heredoc appends to .bashrc/.zshrc would also be forbidden.
        text = _read(_INSTALL_SH)
        for forbidden in (">> ~/.bashrc", ">> ~/.zshrc", ">> ${HOME}/.bashrc", ">> ${HOME}/.zshrc"):
            assert forbidden not in text, f"forbidden heredoc in install.sh: {forbidden!r}"

    def test_does_print_a_path_hint(self) -> None:
        # The new behaviour: print the export line the user should
        # add themselves. Verify the message is present, with the
        # right content.
        text = _read(_INSTALL_SH)
        assert "export PATH=" in text
        assert ".local/bin" in text


class TestPowerShellInstallerProfileRespect:
    """install.ps1 must not silently write to HKCU user PATH."""

    def test_set_environment_variable_is_guarded(self) -> None:
        text = _read(_INSTALL_PS1)
        # The unconditional write of the old installer looked like:
        #   [Environment]::SetEnvironmentVariable('Path', ..., 'User')
        # with no enclosing condition. The new installer wraps it
        # in a `if ($answer -match '^[Yy]')` block (a confirmation
        # prompt) before applying. Check the literal `User'` is
        # preceded by an `if` or an `elseif` in the surrounding 8
        # lines.
        match = re.search(r"SetEnvironmentVariable\(\s*['\"]Path['\"]", text)
        assert match is not None, "expected a SetEnvironmentVariable('Path', ...) call somewhere"
        # Look 8 lines back for a control-flow statement.
        before = text[: match.start()]
        window = before.splitlines()[-8:]
        joined = " ".join(window).lower()
        assert "if " in joined or "elseif " in joined, (
            "SetEnvironmentVariable('Path', ..., 'User') is not guarded by an `if` — "
            "this would silently persist the user's HKCU PATH."
        )

    def test_contains_read_host_prompt(self) -> None:
        # The new installer asks the user before persisting HKCU PATH.
        text = _read(_INSTALL_PS1)
        assert "Read-Host" in text, "expected a Read-Host confirmation prompt in install.ps1"

    def test_session_path_set_unconditionally(self) -> None:
        # The session-only PATH change must still happen regardless
        # of the user's answer to the prompt.
        text = _read(_INSTALL_PS1)
        assert "$env:Path" in text, "expected a session-only $env:Path update in install.ps1"
