# .NET Profile

Loaded when the repository contains `*.sln` or `*.csproj` files.

## Conventions

- Target the .NET version declared in the `TargetFramework` of the projects. Do not assume .NET 8.
- Match the language version declared in `<LangVersion>`. If absent, use the default for the target framework.
- Prefer file-scoped namespaces, `using` directives outside the namespace, and `var` for local variables where the type is apparent.
- Use `record` for DTOs and immutable data. Use `record class` or `record struct` based on value-type intent.
- Use `IReadOnlyList<T>` / `IReadOnlyDictionary<TKey, TValue>` in public APIs unless mutability is required.

## Project layout

- Solutions sit at the repo root. Projects live under `src/`, `tests/`, and optionally `tools/`.
- One project per directory. Project name matches directory name.
- Shared code goes into a project named `*.Shared` or `*.Common` only if there is a concrete consumer for it; otherwise duplicate.

## Build and test

- Build with `dotnet build -c Release`.
- Test with `dotnet test -c Release --no-build`. Honour any filter / logger conventions in the repo.
- Format with `dotnet format` if the repo has a `dotnetformat.json` or `.editorconfig`; otherwise leave formatting alone.

## Dependencies

- Use `Directory.Packages.props` for centralised package versions if the repo has one. Do not create one.
- Do not add a new package without checking whether the functionality is already in the BCL or in an existing dependency.
- Prefer Microsoft-published packages for cross-cutting concerns (logging, hosting, configuration).

## Public API changes

- Any change to a public type or member is a breaking change. Surface it before implementing.
- New public APIs should be `public sealed` by default. Open with `public` only when subclassing is a designed extension point.
- Do not introduce a new public interface for a single implementation.

## Logging and configuration

- Use `Microsoft.Extensions.Logging.ILogger<T>`. Pass `T` as the category-owning class.
- Use `IOptions<T>` for configuration. Do not read configuration directly from `IConfiguration` in business code.
- Log at the lowest level that conveys the event. Information for state changes, Warning for recoverable anomalies, Error for failures.

## Things to avoid

- Do not introduce `Newtonsoft.Json` in a project that already uses `System.Text.Json`.
- Do not use `Task.Run` to "parallelise" code that is already async.
- Do not use `Thread.Sleep`, `Task.Delay` with arbitrary constants, or `ConfigureAwait(false)` in libraries.
- Do not use reflection to access internal members of your own assemblies.
