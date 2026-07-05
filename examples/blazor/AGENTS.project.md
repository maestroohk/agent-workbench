# Blazor example

Example `AGENTS.project.md` for a Blazor Server + WebAssembly hybrid app.

---

## 1. Project overview

`Contoso.IntranetPortal` — a Blazor hybrid application. Server-rendered
pages for the authenticated shell, WebAssembly for the report designer.
Owned by the Internal Tools team.

## 2. Domain rules

- The current user is resolved via `AuthenticationStateProvider` and exposed
  through the `CurrentUser` cascading parameter. Do not read claims directly
  in pages.
- A page must declare a required policy with `[Authorize(Policy = "...")]`
  unless it is the landing page.
- Server-side: never trust client-validated form state. Re-run validation
  in the service layer.

## 3. Conventions specific to this repo

- Pages: `Pages/<Area>/<Page>.razor`.
- Reusable components: `Components/<Name>.razor`.
- Service layer: `Services/`. Each service is a `Scoped` DI registration.
- Cross-cutting state: `State/` (a small set of scoped services that hold
  `IComponent` references for the lifetime of the circuit).

## 4. Non-goals

- Do not introduce MudBlazor, Radzen, or any other UI component library.
  The team has its own design system in `Components/Ui/`.
- Do not use `IJSRuntime` from `OnInitialized`. The DOM may not be ready.
- Do not store tokens in `localStorage` from WebAssembly. Use the cookie
  auth shared with the Server project.

## 5. Test data

- Component tests use bUnit. They run in the standard test project.
- Server-side tests use `WebApplicationFactory<Program>` with the
  `Test` environment.

## 6. Owners

- Auth and identity: `@noor.haddad`.
- Reports (WebAssembly): `@lucas.romero`.
- Server shell: `@yuki.sato`.
