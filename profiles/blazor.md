# Blazor Profile

Loaded when the repository contains `*.csproj` referencing `Microsoft.AspNetCore.Components.*` or `*.razor` files.

## Project layout

- Blazor Server and Blazor WebAssembly share most conventions; the difference is the hosting model.
- Pages live under `Pages/`. Each page is a `.razor` file with an `@page` directive.
- Components live under `Components/` or `Shared/`. Use `Shared/` for components used by the layout, `Components/` for feature components.
- Layout is in `Shared/MainLayout.razor`. The router is in `App.razor`.
- Static assets live under `wwwroot/`. Do not put code under `wwwroot/`.

## Components

- A component is a `.razor` file. Code goes in an `@code` block. Markup is plain HTML with Razor.
- Prefer `partial class` for components that need C# in a separate file.
- Parameter validation lives in `OnInitialized` / `OnParametersSet`, not in the markup.
- Use `EventCallback<T>` for events. Do not expose `Action<T>` from components.

## State

- Use cascading parameters for cross-cutting state (current user, theme, tenant). Do not thread them as explicit parameters.
- Use a state container only when the state is shared by distant components and not naturally cascading. A simple service registered as scoped is usually enough.
- Do not put business state in the URL. The URL is for identity, not for caches.

## Data access

- Use `HttpClient` registered via `IHttpClientFactory`. Do not `new HttpClient()` in components.
- Server-side: prefer direct service calls in scoped services. Do not call `HttpClient` to hit your own server.
- WebAssembly: cache responses when the network is metered. Honour the user's connection.

## Forms and validation

- Use `EditContext` and `DataAnnotations` for form validation.
- Display validation messages with `<ValidationMessage>`. Do not roll custom validation messaging.
- Disable submit buttons while the form is submitting. Use `EditContext.Validate()` only if you need synchronous validation.

## Things to avoid

- Do not call JS interop in `OnInitialized` or `OnAfterRender`'s first render. Use `OnAfterRenderAsync(firstRender: true)` if you must.
- Do not store secrets in WebAssembly assemblies. They are public.
- Do not subscribe to events in `OnAfterRender` without unsubscribing in `IDisposable.Dispose`.
- Do not pass `IEnumerable<T>` from a component to a parent and then enumerate it multiple times. Materialise with `.ToList()` or return `IReadOnlyList<T>`.

## Build and test

- Build with `dotnet build`.
- Test with `bUnit` for component tests, plus the standard `dotnet test` for service tests.
- Format with `dotnet format` if the project has a config for it.
