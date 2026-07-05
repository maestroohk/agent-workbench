# WSO2 MI Profile

Loaded when the repository contains `deployment.toml` or `src/main/wso2mi` directories.

## Project layout

- Synapse artifacts live under `src/main/wso2mi/<artifact>/<name>/`.
- An artifact is a unit of deployable configuration. The directory name is the artifact name.
- Sequence, proxy service, API, endpoint, mediator, and inbound endpoint each have their own subdirectory convention.

## Configuration

- `deployment.toml` is the server-level configuration. Project-level overrides go in `src/main/wso2mi/conf/`.
- Carbon applications are packaged as `.car` files via the Maven `MI Maven Plugin` (groupId `org.wso2.maven`).
- Do not commit built `.car` files. They are build outputs.

## Sequences and proxies

- A sequence file declares the mediators that run in order. Mediator implementations are either inline XML, class mediators, or script mediators.
- A proxy service binds an inbound transport to a sequence. Name proxy services to reflect the inbound service, not the backend.
- An API in WSO2 MI maps HTTP resources to sequences. Use REST-style URLs unless the project has a different convention.

## Endpoints

- Prefer address endpoints with explicit HTTP methods over dynamic endpoints.
- Endpoint timeouts and retry policies are configured in the endpoint definition. Match the SLAs of the backend system.

## Registry and datasources

- Configuration registry entries are stored as files. Do not commit registry mounts under `src/main/wso2mi/registry/`.
- Datasources are configured in `deployment.toml` under `[datasources]`. Reference them by name in mediators.

## Things to avoid

- Do not hand-write class mediators when a stock mediator covers the case. If a class mediator is necessary, add the source under `src/main/java` and reference it.
- Do not embed secrets in sequences. Use the secret manager or a vault.
- Do not modify `axis2.xml` or `synapse.properties` directly. Use `deployment.toml` overrides.

## Build and deploy

- Build with `mvn clean package`. Output is `target/<artifact>-<version>.car`.
- Deploy by dropping the `.car` into `<MI_HOME>/repository/deployment/server/carbonapps/` on the target server, or via the management API.
- Validate the project with the WSO2 MI for VS Code extension's "Form View" before committing XML changes.
