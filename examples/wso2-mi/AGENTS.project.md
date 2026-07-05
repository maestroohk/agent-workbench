# WSO2 MI example

Example `AGENTS.project.md` for a WSO2 Micro Integrator project.

---

## 1. Project overview

`Contoso.IntegrationGateway` — a WSO2 MI 4.2 project that brokers traffic
between internal systems and external partners. Built as a Maven project; the
`pom.xml` declares the WSO2 MI plugin.

## 2. Domain rules

- A mediation flow that touches a partner system must log the partner ID and
  the message ID at the start and end of the flow.
- A sequence that mutates the message body must include a payload hash in
  the audit log.
- A failure in a downstream call must produce a single, typed fault, not
  the raw error string.

## 3. Conventions specific to this repo

- Sequences: `src/main/wso2mi/sequences/<name>/<name>.xml`.
- Endpoints: `src/main/wso2mi/endpoints/<name>/<name>.xml`.
- Custom mediators: `src/main/java/com/contoso/mediators/...`.
- Each artifact has an `artifact.xml` describing its dependencies.

## 4. Non-goals

- Do not bypass the governance registry. All artifacts must be deployed via
  the `.car` produced by the Maven build.
- Do not introduce `script` mediators. They are difficult to test and
  unmaintainable.
- Do not edit `axis2.xml` or `synapse.properties`. Use `deployment.toml`
  overrides in `src/main/wso2mi/conf/`.

## 5. Test data

- Integration tests run against a containerised MI server. The image tag is
  pinned in `pom.xml`.
- Mock backends live in `src/test/resources/mock-services/`. They are
  WireMock instances.

## 6. Owners

- Integration patterns: `@ben.tanaka`.
- Security / partners: `@ola.adekunle`.
- Build / deploy: `@maya.iyer`.
