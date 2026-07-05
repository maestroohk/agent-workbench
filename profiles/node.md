# Node.js Profile

Loaded when the repository contains `package.json` without a frontend framework, or when explicitly tagged for backend Node.js.

## Project layout

- Entry point is declared in `package.json` `"main"` or `"exports"`. Source code lives under `src/` unless the project uses a different convention.
- One module per file. Filename matches the primary export.
- A "service" is a module that exposes a class or a factory. A "controller" handles HTTP and delegates to services. Keep controllers thin.

## Language

- TypeScript is the default. If the project uses JavaScript with JSDoc, follow the existing convention.
- Target the Node version declared in `engines.node` and `.nvmrc`. Do not assume LTS.
- Match the module system in the project: ESM (`"type": "module"`) or CJS. Do not mix within a single package.

## Dependencies

- Use the package manager pinned in `packageManager` or, in its absence, the lockfile in the repo (`pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`).
- Do not add a runtime dependency for functionality the standard library covers.
- Dev dependencies for build, test, lint tools. Runtime dependencies for libraries the app imports.

## Async

- Use `async` / `await` everywhere. Do not chain `.then()` callbacks in application code.
- Use `AbortController` for cancellable operations.
- Do not swallow promise rejections. Every catch should either rethrow, log with context, or convert to a typed error.

## Error handling

- Throw `Error` subclasses with messages that include the operation and inputs that produced the failure.
- At process boundaries (HTTP, queue consumer), translate to the wire format the protocol expects. Do not leak stack traces in production responses.

## HTTP

- Use the framework's router and middleware. Do not write raw `http.createServer` for an HTTP service.
- Validate request bodies with a schema library. Do not trust the client.

## Testing

- Use the test runner declared in `package.json` (`jest`, `vitest`, `node:test`). Do not introduce a second runner.
- Test names describe behaviour, not implementation. Do not name tests after the function they test.
- Mock at the network boundary or the module boundary. Do not mock time with real timers.

## Things to avoid

- Do not commit `.env` files. Use `.env.example` for documentation.
- Do not log secrets, even at debug level.
- Do not use `setTimeout` to "wait for the database" — use a real retry / health check.
- Do not use `eval`, `vm`, or `Function` on dynamic input.
