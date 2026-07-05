# Python Profile

Loaded when the repository contains `pyproject.toml`, `requirements.txt`, `setup.py`, `setup.cfg`, or `Pipfile`.

## Project layout

- Source code lives under a package directory whose name matches the project name. Tests live under `tests/` mirroring the source layout.
- A "module" is one file. A "package" is a directory with `__init__.py`. If the project uses implicit namespace packages, follow that.
- Entry points are declared in `pyproject.toml` `[project.scripts]`. Do not add a `main.py` unless the project already has one.

## Language version

- Target the Python version declared in `pyproject.toml` `requires-python` or in `setup.py`. Do not assume 3.12.
- Use type hints on public functions. They are documentation as much as enforcement.
- Use `from __future__ import annotations` only if the project already uses it.

## Dependencies

- Use the package manager declared by the lockfile / `pyproject.toml` (`uv.lock`, `poetry.lock`, `Pipfile.lock`, or none).
- Do not add a dependency for a single utility function. Inline it.
- Pin transitive constraints in `pyproject.toml` only when the project already does so.

## Async

- Use `async` / `await` consistently within an async code path. Do not call sync blocking I/O from an async function.
- Use `asyncio.TaskGroup` (3.11+) or `trio` for structured concurrency. Do not fire-and-forget tasks.

## Data

- Use `pydantic` for boundary validation if the project already uses it. Otherwise, use the project's existing validation approach.
- Database access through a session / connection per request. Do not share connections across threads.
- Migrations are committed alongside the model change. Do not commit a model change without a migration.

## Testing

- Use the test runner declared in `pyproject.toml` (`pytest`, `unittest`). Do not introduce a second runner.
- Tests are functions, not classes, unless the project uses `unittest.TestCase` style.
- Fixtures: use `pytest` fixtures scoped appropriately. Do not create module-level mutable state.

## Things to avoid

- Do not use `print` for logging. Use `logging` or `structlog` (whichever the project uses).
- Do not catch `Exception` broadly. Catch the specific exceptions you can handle.
- Do not use mutable default arguments.
- Do not use `os.path`. Use `pathlib.Path`.
- Do not use `subprocess.run(shell=True)`. Pass a list of arguments.
