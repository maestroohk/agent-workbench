"""Scan a repository and generate `.agent/` summaries.

The summaries are intentionally short. They are designed to be loaded into an
AI system prompt, not to be read end-to-end by a human.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from detect_stack import detect_stack
from utils import (
    find_repo_root,
    info,
    list_subdirectories,
    read_text,
    truncate,
    write_text,
)


AGENT_DIR_NAME = ".agent"

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "bin",
    "obj",
    "target",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".venv",
    "venv",
    "__pycache__",
    ".gradle",
    ".idea",
    ".vs",
    ".vscode",
    ".agent",
    ".terraform",
}

EXCLUDE_FILE_SUFFIXES = {
    ".min.js",
    ".min.css",
    ".map",
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".class",
    ".jar",
    ".war",
    ".dll",
    ".exe",
    ".so",
    ".dylib",
    ".bin",
}


def _iter_files(root: Path):
    for current, dirs, files in _safe_walk(root):
        for name in files:
            yield Path(current) / name


def _safe_walk(root: Path):
    import os
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        yield current, dirs, files


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _is_textual(path: Path) -> bool:
    if path.suffix.lower() in EXCLUDE_FILE_SUFFIXES:
        return False
    if path.stat().st_size > 256 * 1024:
        return False
    try:
        with path.open("rb") as handle:
            sample = handle.read(4096)
        sample.decode("utf-8")
        return True
    except (UnicodeDecodeError, OSError):
        return False


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _read_lines(path: Path) -> list[str]:
    return read_text(path).splitlines()


def detect_entry_points(repo: Path) -> list[str]:
    """Best-effort guess at the application's entry points."""
    candidates = [
        "src/main.py",
        "src/main.ts",
        "src/index.ts",
        "src/index.js",
        "src/index.tsx",
        "src/main.tsx",
        "src/main.jsx",
        "src/App.tsx",
        "src/App.jsx",
        "Program.cs",
        "Startup.cs",
        "app/main.py",
        "main.py",
        "index.js",
        "server.js",
        "app.py",
    ]
    found: list[str] = []
    for rel in candidates:
        if (repo / rel).is_file():
            found.append(rel)
    # Look for `main`/`module` in package.json
    pkg = repo / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(read_text(pkg))
        except json.JSONDecodeError:
            data = {}
        for key in ("main", "module", "source", "bin"):
            value = data.get(key)
            if isinstance(value, str) and (repo / value).is_file():
                found.append(value)
    return found


def detect_package_managers(repo: Path) -> list[str]:
    managers: list[str] = []
    checks = {
        "npm": "package-lock.json",
        "pnpm": "pnpm-lock.yaml",
        "yarn": "yarn.lock",
        "bun": "bun.lockb",
        "pip": "requirements.txt",
        "poetry": "poetry.lock",
        "uv": "uv.lock",
        "pipenv": "Pipfile.lock",
        "maven": "pom.xml",
        "gradle": "build.gradle",
        "dotnet": "*.sln",
    }
    for manager, marker in checks.items():
        if marker == "*.sln":
            if any(repo.glob("*.sln")):
                managers.append(manager)
            continue
        if (repo / marker).is_file():
            managers.append(manager)
    return managers


def detect_test_frameworks(repo: Path) -> list[str]:
    found: list[str] = []
    pkg = repo / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(read_text(pkg))
        except json.JSONDecodeError:
            data = {}
        for key in ("devDependencies", "dependencies"):
            deps = data.get(key) or {}
            for name in ("jest", "vitest", "mocha", "playwright", "cypress", "@playwright/test"):
                if name in deps:
                    found.append(name)
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        text = read_text(pyproject)
        for name in ("pytest", "unittest", "tox", "nox"):
            if name in text:
                found.append(name)
    for csproj in repo.glob("**/*.csproj"):
        text = read_text(csproj)
        for marker in ("xunit", "nunit", "MSTest.TestFramework", "bunit"):
            if marker.lower() in text.lower():
                found.append(marker)
    for pom in repo.glob("**/pom.xml"):
        text = read_text(pom).lower()
        for marker in ("junit-jupiter", "junit", "testng", "cucumber"):
            if marker in text:
                found.append(marker)
    return sorted(set(found))


def detect_ci(repo: Path) -> list[str]:
    found: list[str] = []
    github = repo / ".github" / "workflows"
    if github.is_dir():
        for wf in github.glob("*.yml"):
            found.append(f"github: {wf.name}")
        for wf in github.glob("*.yaml"):
            found.append(f"github: {wf.name}")
    for name in ("azure-pipelines.yml", ".gitlab-ci.yml", "Jenkinsfile", "bitbucket-pipelines.yml"):
        if (repo / name).is_file():
            found.append(name)
    return found


def detect_docker(repo: Path) -> list[str]:
    found: list[str] = []
    for marker in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", ".dockerignore"):
        if (repo / marker).is_file():
            found.append(marker)
    return found


def detect_documentation(repo: Path) -> list[str]:
    found: list[str] = []
    for name in ("README.md", "README.rst", "README", "CONTRIBUTING.md", "CHANGELOG.md", "ARCHITECTURE.md"):
        if (repo / name).is_file():
            found.append(name)
    docs = repo / "docs"
    if docs.is_dir():
        for f in sorted(docs.glob("*.md"))[:10]:
            found.append(f"docs/{f.name}")
    return found


def detect_config(repo: Path) -> list[str]:
    candidates = [
        ".editorconfig",
        ".gitignore",
        ".prettierrc",
        ".prettierrc.json",
        ".eslintrc",
        ".eslintrc.json",
        ".eslintrc.js",
        "tsconfig.json",
        "jsconfig.json",
        "vite.config.ts",
        "vite.config.js",
        "next.config.js",
        "next.config.ts",
        "pyproject.toml",
        "ruff.toml",
        ".ruff.toml",
        "tox.ini",
        "setup.cfg",
        "Directory.Build.props",
        "Directory.Packages.props",
        "global.json",
    ]
    return [c for c in candidates if (repo / c).is_file()]


def language_breakdown(repo: Path) -> dict[str, int]:
    """Count lines of code per language, capped at common extensions."""
    ext_to_lang = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".cs": "C#",
        ".razor": "Razor",
        ".java": "Java",
        ".kt": "Kotlin",
        ".go": "Go",
        ".rs": "Rust",
        ".rb": "Ruby",
        ".php": "PHP",
        ".xml": "XML",
        ".json": "JSON",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".md": "Markdown",
        ".sql": "SQL",
        ".html": "HTML",
        ".css": "CSS",
        ".scss": "SCSS",
    }
    counts: Counter = Counter()
    for path in _iter_files(repo):
        lang = ext_to_lang.get(path.suffix.lower())
        if not lang:
            continue
        counts[lang] += _line_count(path)
    return dict(counts.most_common())


def build_repo_summary(repo: Path) -> str:
    parts: list[str] = []
    name = repo.name
    parts.append(f"# Repository summary: {name}")
    parts.append("")
    parts.append("This summary is auto-generated by `agent-scan`. Do not edit by hand.")
    parts.append("")
    parts.append("## Top-level structure")
    parts.append("")
    subdirs = sorted(
        d.name
        for d in repo.iterdir()
        if d.is_dir() and d.name not in EXCLUDE_DIRS
    )
    files = sorted(
        f.name
        for f in repo.iterdir()
        if f.is_file() and f.suffix.lower() not in EXCLUDE_FILE_SUFFIXES
    )[:50]
    parts.append("Directories:")
    if subdirs:
        for d in subdirs:
            parts.append(f"- {d}/")
    else:
        parts.append("- (none)")
    parts.append("")
    parts.append("Top-level files (first 50):")
    if files:
        for f in files:
            parts.append(f"- {f}")
    else:
        parts.append("- (none)")
    parts.append("")
    parts.append("## Languages (by lines of code)")
    parts.append("")
    langs = language_breakdown(repo)
    if langs:
        total = sum(langs.values()) or 1
        for lang, lines in langs.items():
            pct = (lines / total) * 100
            parts.append(f"- {lang}: {lines:,} lines ({pct:.1f}%)")
    else:
        parts.append("- (no source files found)")
    parts.append("")
    return "\n".join(parts) + "\n"


def build_architecture(repo: Path) -> str:
    parts: list[str] = []
    parts.append(f"# Architecture: {repo.name}")
    parts.append("")
    parts.append("Auto-generated by `agent-scan`. Top-level layout and entry points only.")
    parts.append("")
    parts.append("## Top-level modules")
    parts.append("")
    for d in sorted(repo.iterdir()):
        if d.is_dir() and d.name not in EXCLUDE_DIRS:
            description = ""
            readme = d / "README.md"
            if readme.is_file():
                first = read_text(readme).splitlines()
                for line in first[:5]:
                    line = line.strip().lstrip("#").strip()
                    if line:
                        description = line
                        break
            suffix = f" -- {description}" if description else ""
            parts.append(f"- `{d.name}/`{suffix}")
    parts.append("")
    parts.append("## Entry points")
    parts.append("")
    for entry in detect_entry_points(repo):
        parts.append(f"- `{entry}`")
    if not detect_entry_points(repo):
        parts.append("- (none detected)")
    parts.append("")
    parts.append("## Detected stack")
    parts.append("")
    matches = detect_stack(repo)
    if matches:
        for m in matches:
            parts.append(f"- **{m.name}**: {', '.join(m.evidence)}")
    else:
        parts.append("- (no profiles matched)")
    parts.append("")
    return "\n".join(parts) + "\n"


def build_build(repo: Path) -> str:
    parts: list[str] = []
    parts.append(f"# Build: {repo.name}")
    parts.append("")
    parts.append("## Package managers")
    parts.append("")
    managers = detect_package_managers(repo)
    if managers:
        for m in managers:
            parts.append(f"- {m}")
    else:
        parts.append("- (none detected)")
    parts.append("")
    parts.append("## Container")
    parts.append("")
    docker = detect_docker(repo)
    if docker:
        for d in docker:
            parts.append(f"- {d}")
    else:
        parts.append("- (no container files)")
    parts.append("")
    parts.append("## CI/CD")
    parts.append("")
    ci = detect_ci(repo)
    if ci:
        for c in ci:
            parts.append(f"- {c}")
    else:
        parts.append("- (no CI detected)")
    parts.append("")
    return "\n".join(parts) + "\n"


def build_commands(repo: Path) -> str:
    parts: list[str] = []
    parts.append(f"# Commands: {repo.name}")
    parts.append("")
    parts.append("These are inferred from the repository. Run from the repo root.")
    parts.append("")
    managers = detect_package_managers(repo)
    if "npm" in managers or "pnpm" in managers or "yarn" in managers or "bun" in managers:
        pm = "pnpm" if "pnpm" in managers else "yarn" if "yarn" in managers else "bun" if "bun" in managers else "npm"
        parts.append("## Node")
        parts.append("")
        parts.append(f"- Install: `{pm} install`")
        parts.append(f"- Build: `{pm} run build` (if defined)")
        parts.append(f"- Test: `{pm} test` (if defined)")
        parts.append("")
    if "uv" in managers or "poetry" in managers or "pipenv" in managers or "pip" in managers or "pyproject.toml" in (p.name for p in repo.iterdir()):
        pm = "uv" if "uv" in managers else "poetry" if "poetry" in managers else "pipenv" if "pipenv" in managers else "pip"
        parts.append("## Python")
        parts.append("")
        parts.append(f"- Install: `{pm} install`")
        parts.append(f"- Test: `{pm} run pytest` (or `pytest` directly)")
        parts.append("")
    if "maven" in managers:
        parts.append("## Maven")
        parts.append("")
        parts.append("- Build: `mvn -B package`")
        parts.append("- Test: `mvn -B test`")
        parts.append("")
    if "gradle" in managers:
        parts.append("## Gradle")
        parts.append("")
        parts.append("- Build: `./gradlew build`")
        parts.append("- Test: `./gradlew test`")
        parts.append("")
    if "dotnet" in managers:
        parts.append("## .NET")
        parts.append("")
        parts.append("- Build: `dotnet build -c Release`")
        parts.append("- Test: `dotnet test -c Release --no-build`")
        parts.append("")
    if detect_docker(repo):
        parts.append("## Docker")
        parts.append("")
        parts.append("- Compose up: `docker compose up -d`")
        parts.append("- Build image: `docker build -t <name> .`")
        parts.append("")
    return "\n".join(parts) + "\n"


def build_dependencies(repo: Path) -> str:
    parts: list[str] = []
    parts.append(f"# Dependencies: {repo.name}")
    parts.append("")
    pkg = repo / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(read_text(pkg))
        except json.JSONDecodeError:
            data = {}
        for key in ("dependencies", "devDependencies"):
            deps = data.get(key) or {}
            if not deps:
                continue
            parts.append(f"## {key}")
            parts.append("")
            for name, version in sorted(deps.items()):
                parts.append(f"- {name}@{version}")
            parts.append("")
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        text = read_text(pyproject)
        # Naive section extraction -- sufficient for a summary.
        in_deps = False
        current: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                if in_deps and current:
                    for entry in current:
                        parts.append(f"- {entry}")
                    current = []
                in_deps = stripped in ("[tool.poetry.dependencies]", "[tool.poetry.dev-dependencies]", "[project.dependencies]", "[dependency-groups]")
                if in_deps:
                    parts.append(f"## {stripped[1:-1]}")
                    parts.append("")
            elif in_deps and "=" in stripped:
                current.append(stripped)
        if in_deps and current:
            for entry in current:
                parts.append(f"- {entry}")
            parts.append("")
    if not (pkg.is_file() or pyproject.is_file()):
        parts.append("- (no package.json or pyproject.toml found)")
        parts.append("")
    return "\n".join(parts) + "\n"


def build_coding_style(repo: Path) -> str:
    parts: list[str] = []
    parts.append(f"# Coding style: {repo.name}")
    parts.append("")
    rules: list[str] = []
    if (repo / ".editorconfig").is_file():
        rules.append("Honour `.editorconfig`.")
    if (repo / ".prettierrc").is_file() or (repo / ".prettierrc.json").is_file():
        rules.append("Formatting via Prettier.")
    if (repo / "ruff.toml").is_file() or (repo / ".ruff.toml").is_file():
        rules.append("Linting via Ruff.")
    if (repo / ".eslintrc").is_file() or (repo / ".eslintrc.json").is_file() or (repo / ".eslintrc.js").is_file():
        rules.append("Linting via ESLint.")
    if (repo / "tsconfig.json").is_file():
        rules.append("TypeScript via `tsconfig.json`.")
    if (repo / "Directory.Build.props").is_file():
        rules.append("Centralised MSBuild properties in `Directory.Build.props`.")
    if not rules:
        rules.append("No formatting or linting config detected; match the surrounding code.")
    for rule in rules:
        parts.append(f"- {rule}")
    parts.append("")
    parts.append("## Comment policy")
    parts.append("")
    parts.append("- Do not add comments unless documenting a non-obvious business rule or external constraint.")
    parts.append("- Prefer expressive naming over comments.")
    parts.append("")
    return "\n".join(parts) + "\n"


SUMMARIES = {
    "repo-summary.md": build_repo_summary,
    "architecture.md": build_architecture,
    "build.md": build_build,
    "commands.md": build_commands,
    "dependencies.md": build_dependencies,
    "coding-style.md": build_coding_style,
}


def scan(repo: Optional[Path] = None) -> Path:
    """Generate the `.agent/` summaries. Returns the output directory."""
    target = (repo or Path.cwd()).resolve()
    if not (target / AGENT_DIR_NAME.lstrip(".")).exists():
        # tolerate both `.agent` and `agent` for the rare filesystem that strips dots
        pass
    out_dir = target / AGENT_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename, builder in SUMMARIES.items():
        path = out_dir / filename
        content = builder(target)
        write_text(path, content)
        info(f"wrote {path.relative_to(target)}")
    info(f"scan complete: {out_dir}")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Scan a repository and write .agent/ summaries.")
    parser.add_argument("--repo", type=Path, default=None, help="Repository root (auto-detected).")
    args = parser.parse_args(argv)
    target = (args.repo or find_repo_root()).resolve()
    scan(target)
    return 0


if __name__ == "__main__":
    main()
