"""Detect which technology profiles apply to a repository.

Detection is evidence-based: a profile is loaded only if a known marker file
exists in the repository. Each match carries the evidence so the prompt
assembler can show the user what was found.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from utils import StackMatch, workbench_root


@dataclass
class Detector:
    """A single technology profile and the markers that activate it."""

    name: str
    profile_filename: str
    markers: list[str]
    # Some technologies can be detected by file contents (e.g. `package.json`
    # with `react` in dependencies). Each predicate returns evidence strings.
    predicates: list[Callable[[Path], list[str]]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.predicates is None:
            self.predicates = []


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _has_react(repo: Path) -> list[str]:
    pkg = repo / "package.json"
    if not pkg.is_file():
        return []
    text = _read(pkg).lower()
    if '"react"' not in text and '"react-dom"' not in text:
        return []
    evidence = ["package.json declares react"]
    if (repo / "vite.config.ts").is_file() or (repo / "vite.config.js").is_file():
        evidence.append("vite.config present")
    if (repo / "next.config.js").is_file() or (repo / "next.config.ts").is_file():
        evidence.append("next.config present")
    return evidence


def _has_blazor(repo: Path) -> list[str]:
    evidence: list[str] = []
    for csproj in repo.rglob("*.csproj"):
        text = _read(csproj).lower()
        if "microsoft.aspnetcore.components" in text:
            evidence.append(f"{csproj.relative_to(repo)} references Blazor")
            break
    for razor in repo.rglob("*.razor"):
        evidence.append(f"razor file present: {razor.relative_to(repo)}")
        break
    return evidence


def _has_dotnet(repo: Path) -> list[str]:
    evidence: list[str] = []
    for sln in repo.rglob("*.sln"):
        evidence.append(f"solution: {sln.relative_to(repo)}")
    for csproj in repo.rglob("*.csproj"):
        evidence.append(f"project: {csproj.relative_to(repo)}")
    return evidence


def _has_wso2(repo: Path) -> list[str]:
    evidence: list[str] = []
    if (repo / "deployment.toml").is_file():
        evidence.append("deployment.toml present")
    for candidate in repo.rglob("src/main/wso2mi"):
        if candidate.is_dir():
            evidence.append(f"wso2mi project: {candidate.relative_to(repo)}")
            break
    return evidence


def _has_angular(repo: Path) -> list[str]:
    if (repo / "angular.json").is_file():
        return ["angular.json present"]
    return []


def _has_node(repo: Path) -> list[str]:
    pkg = repo / "package.json"
    if not pkg.is_file():
        return []
    if _has_react(repo) or _has_angular(repo):
        return []
    return ["package.json present (no frontend framework detected)"]


def _has_python(repo: Path) -> list[str]:
    evidence: list[str] = []
    for marker in ("pyproject.toml", "requirements.txt", "Pipfile", "setup.py", "setup.cfg"):
        if (repo / marker).is_file():
            evidence.append(f"{marker} present")
    return evidence


def _has_docker(repo: Path) -> list[str]:
    evidence: list[str] = []
    for marker in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", ".dockerignore"):
        if (repo / marker).is_file():
            evidence.append(f"{marker} present")
    return evidence


def _has_java(repo: Path) -> list[str]:
    evidence: list[str] = []
    for marker in ("pom.xml", "build.gradle", "build.gradle.kts"):
        if (repo / marker).is_file():
            evidence.append(f"{marker} present")
    return evidence


def _has_mysql(repo: Path) -> list[str]:
    evidence: list[str] = []
    if (repo / "my.cnf").is_file():
        evidence.append("my.cnf present")
    initdb = repo / "docker-entrypoint-initdb.d"
    if initdb.is_dir() and any(initdb.iterdir()):
        evidence.append("docker-entrypoint-initdb.d present")
    migrations = repo / "migrations"
    if migrations.is_dir():
        for sql in migrations.glob("*.sql"):
            text = _read(sql).lower()
            if "mysql" in text or "innodb" in text:
                evidence.append(f"migration references MySQL: {sql.relative_to(repo)}")
                break
    return evidence


DETECTORS: list[Detector] = [
    Detector("blazor", "blazor.md", [], [_has_blazor]),
    Detector("dotnet", "dotnet.md", [], [_has_dotnet]),
    Detector("wso2-mi", "wso2-mi.md", [], [_has_wso2]),
    Detector("react", "react.md", [], [_has_react]),
    Detector("angular", "angular.md", [], [_has_angular]),
    Detector("node", "node.md", [], [_has_node]),
    Detector("python", "python.md", [], [_has_python]),
    Detector("java", "java.md", [], [_has_java]),
    Detector("docker", "docker.md", [], [_has_docker]),
    Detector("mysql", "mysql.md", [], [_has_mysql]),
]


def detect_stack(repo: Path) -> list[StackMatch]:
    """Return all matching profiles for `repo`, ordered by detector list order."""
    root = workbench_root()
    profiles_dir = root / "profiles"
    matches: list[StackMatch] = []
    for detector in DETECTORS:
        evidence: list[str] = []
        for predicate in detector.predicates:
            evidence.extend(predicate(repo))
        if not evidence:
            continue
        profile_path = profiles_dir / detector.profile_filename
        if not profile_path.is_file():
            continue
        matches.append(StackMatch(name=detector.name, profile_path=profile_path, evidence=evidence))
    return matches


def detect_stack_names(repo: Path) -> list[str]:
    """Convenience: just the names of the matched profiles."""
    return [m.name for m in detect_stack(repo)]


if __name__ == "__main__":
    import sys
    from utils import find_repo_root

    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else find_repo_root()
    matches = detect_stack(target)
    if not matches:
        print(f"no profiles matched for {target}")
    for match in matches:
        print(f"- {match.name}: {match.profile_path}")
        for item in match.evidence:
            print(f"    {item}")
