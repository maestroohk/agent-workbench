# Angular Profile

Loaded when the repository contains `angular.json` and an Angular workspace.

## Project layout

- A workspace contains applications (`projects/`, or top-level for single-app workspaces) and libraries (`projects/<lib>`).
- A library is the unit of reuse. If two unrelated features share code, that code belongs in a library, not in `shared/`.
- One feature module / standalone component tree per feature area. Co-locate templates, styles, and specs.

## Components

- Use standalone components by default. NgModules are only justified when the existing codebase uses them.
- Use `ChangeDetectionStrategy.OnPush` unless the component genuinely needs default change detection.
- Inputs are `input()` / `input.required<T>()`. Outputs are `output<T>()`.
- Do not use `@Input()` / `@Output()` decorators in new code. They are deprecated for new code.

## Templates

- Templates are inline by default. External templates only when the template is large and the project uses them consistently.
- Use the new control flow (`@if`, `@for`, `@switch`) instead of `*ngIf`, `*ngFor`, `*ngSwitch`.
- Pipes are pure by default. Mark a pipe `pure: false` only with a reason.

## State

- Use Angular signals for component-local state. Use a service with `signal()` for shared state.
- RxJS is for streams. Do not use it as a state container.
- Do not introduce NgRx unless the app already has a non-trivial state graph that justifies it.

## Routing

- Use functional route guards (`CanActivateFn`) and resolvers. Class-based guards are deprecated for new code.
- Lazy-load feature routes with `loadChildren` / `loadComponent`.

## Forms

- Reactive forms for anything beyond trivial. Template-driven forms only when the form is purely presentational.
- Use typed forms (`FormGroup<T>`, `FormControl<T>`).

## HTTP

- Use `HttpClient` with typed responses. Do not use `any` as a response type.
- Use interceptors for cross-cutting concerns (auth, error reporting, logging). Keep them small.
- Cancellation: pass an `Observable` consumer that completes. Do not write manual `unsubscribe` for components — use `async` pipe or `takeUntilDestroyed`.

## Testing

- TestBed for component tests, plus plain `describe` / `it` for services and pure logic.
- Do not test private methods. Test through the public surface.
- Use the Angular Testing Library helpers when the project already uses them.

## Things to avoid

- Do not use `any`. Use `unknown` and narrow it.
- Do not subscribe in components without `async` pipe / `takeUntilDestroyed`.
- Do not introduce a UI library to "modernise" an existing design system without coordination.
- Do not edit generated files under `dist/`, `.angular/`, or `node_modules/`.
