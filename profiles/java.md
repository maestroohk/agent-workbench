# Java Profile

Loaded when the repository contains `pom.xml` or `build.gradle` (or `build.gradle.kts`).

## Build system

- Maven: respect the project structure. Modules live as siblings with their own `pom.xml`. Parent POM at the root.
- Gradle: use the Kotlin DSL (`build.gradle.kts`) only if the project already does. Otherwise stay on Groovy.
- Do not switch build systems as part of a feature change.

## Language version

- Match the source / target declared in the build file. Do not assume Java 21.
- Use the language features available at that level. Do not use preview features without opt-in.

## Project layout

- `src/main/java` for sources, `src/test/java` for tests, `src/main/resources` for resources.
- Package name mirrors the directory structure. One top-level package per module.
- Public API lives in the top-level package or a `api` subpackage. Implementation in `internal`, `impl`, or unexported packages.

## Dependencies

- Add dependencies to the build file. Do not drop JARs into `lib/`.
- Use the dependency management section of the parent POM to pin versions. Do not pin versions in individual modules unless the parent has none.
- Use the BOM the project provides. Do not introduce a second BOM.

## Testing

- JUnit 5 by default. If the project uses JUnit 4, follow that.
- Use the assertion library the project uses (AssertJ, Hamcrest, plain JUnit). Do not introduce a new one.
- Integration tests: use the project's naming convention (`*IT`, `*IntegrationTest`). Honour failsafe / surefire separation.

## Logging and configuration

- Use SLF4J. Do not use `System.out.println` or `java.util.logging` in new code.
- Use the project's configuration mechanism (`application.yml`, `application.properties`, etc.). Do not read environment variables directly in business code.

## Things to avoid

- Do not use raw types. Use generics.
- Do not catch `Throwable` or `Exception` broadly. Catch specific exceptions.
- Do not commit IDE-specific files (`.idea/`, `.vscode/`-Java-specific settings) unless the project already does.
- Do not use `Date` / `Calendar`. Use `java.time`.
- Do not write `equals` / `hashCode` by hand. Use a record, Lombok, or a generator.
