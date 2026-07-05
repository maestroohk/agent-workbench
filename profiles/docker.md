# Docker Profile

Loaded when the repository contains a `Dockerfile` or `docker-compose.{yml,yaml}`.

## Image design

- One process per container. Use a supervisor only when the existing pattern requires it.
- Use a specific base image tag, not `:latest`. Pin by digest if reproducibility matters.
- Multi-stage builds for compiled languages. Final stage contains only the runtime artefacts.
- Run as a non-root user. The `USER` directive must be set explicitly.

## Layering

- Order `RUN` steps from least-changing to most-changing. Build cache is invalidated by any change above.
- Copy `package.json` / `pyproject.toml` / `go.mod` before the source, run the install step, then copy the source. This is the standard pattern.
- `.dockerignore` should exclude `.git`, `node_modules`, `target`, `bin`, `obj`, `.venv`, `__pycache__`, and the build output directories of the project.

## Compose

- One `docker-compose.yml` for local development. Override files for environment-specific configuration.
- Health checks: define a `healthcheck` for any service that other services depend on. Do not let dependents start before the dependency is healthy.
- Named volumes for stateful data. Bind mounts for development hot-reload only.

## Networking

- Services on the same compose network can reach each other by service name. Do not hard-code IPs.
- Expose ports to the host only when the service is meant to be reached from outside. Use `expose` for internal-only ports.

## Secrets

- Use Docker secrets or an external secret manager. Do not bake secrets into images.
- Use `${VAR}` substitution from a `.env` file in development. Commit `.env.example`, not `.env`.
- Do not log secrets.

## Things to avoid

- Do not run `apt-get update` without `apt-get install` (and `rm -rf /var/lib/apt/lists/*`) in the same `RUN` to keep layers small.
- Do not use `ADD` for remote URLs or local tarballs unless you specifically need its extraction behaviour. Prefer `COPY` + explicit extraction.
- Do not use `MAINTAINER` (deprecated). Use a `LABEL maintainer=...` if you must.
- Do not set `ENV` for secrets. Use build args with a secret mount, or runtime injection.

## Build and push

- Build with `docker buildx build` for multi-platform images. Tag with both the version and `latest` only if the project uses that pattern.
- Scan images with `docker scout` or `trivy` in CI.
