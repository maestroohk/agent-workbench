# React Profile

Loaded when the repository contains `package.json` with `react` in dependencies and either `vite.config.*`, `next.config.*`, or a `src/App.{tsx,jsx}` file.

## Project layout

- Source code lives under `src/`. Tests live next to source as `*.test.{ts,tsx}` or in `__tests__/`.
- A "feature" is a directory under `src/features/<feature>/` containing its components, hooks, types, and tests.
- Shared UI primitives live under `src/components/` or `src/ui/`. Choose one and stay consistent.
- Hooks that are not feature-specific live under `src/hooks/`.

## Components

- Function components only. Hooks only.
- Use TypeScript for everything. Do not mix `.js` and `.ts` in the same project.
- One component per file. Filename matches the component name in PascalCase.
- Default export is fine for page-level components. Named exports for everything else.
- Use `React.memo` only when profiling shows a render is expensive. Do not memo preemptively.
- Use `useCallback` / `useMemo` only when there is a documented reason.

## State

- Local state: `useState` / `useReducer`. Server state: a query library (React Query, SWR, or your framework's equivalent). Global UI state: a context or a small store.
- Do not put server data in Redux / Zustand / Jotai. Use a query library and let it own the cache.
- A reducer is justified when the next state depends on the previous state in a non-trivial way. Otherwise `useState` is enough.

## Data fetching

- Use the project's query library consistently. Do not mix `fetch` and the query library in the same file.
- Cancellation: trust the query library. Do not write your own `AbortController` plumbing.
- Errors: surface them in the UI. Do not swallow them in `try/catch` blocks that just log.

## Styling

- If the project uses Tailwind, follow the existing class order conventions.
- If the project uses CSS Modules, do not introduce a different system.
- Do not introduce inline styles for layout that the existing system handles.

## Testing

- Use the testing library that matches the project's framework (React Testing Library for plain React, `@testing-library/react` for Next.js, etc.).
- Test behaviour, not implementation. Do not assert on internal state, hook call counts, or render trees.
- Mock at the network boundary. Do not mock modules.

## Things to avoid

- Do not add a state management library to "future-proof" the app.
- Do not use `useEffect` for derived state. Compute it in render.
- Do not use index files (`index.ts`) as a dumping ground. Export named symbols from the module that defines them.
- Do not commit `console.log` to `main`.
