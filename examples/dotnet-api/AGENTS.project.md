# .NET API example

A minimal example showing what a real `AGENTS.project.md` looks like for a .NET
Web API project. Drop this in the project root and adjust.

---

## 1. Project overview

`Contoso.OrderService` — a .NET 8 Web API that owns the order lifecycle. Owned
by the Orders squad. Talks to Postgres, RabbitMQ, and the Payment service over
gRPC.

## 2. Domain rules

- An order is `Pending` until payment is captured. Do not invent intermediate
  states.
- The `Order.Status` column is the source of truth. Do not derive it from
  payment or shipment tables.
- The `discount_amount` column must equal `unit_price * quantity * discount_rate`
  rounded to two decimal places. Do not change this rounding.

## 3. Conventions specific to this repo

- All public DTOs live in `src/Contoso.OrderService.Contracts/`.
- Endpoints are minimal API endpoints registered in `Endpoints/` by feature.
- Database access goes through `OrderDbContext`. Do not introduce a second
  context.
- Migrations are append-only. Never edit a committed migration.

## 4. Non-goals

- Do not introduce MediatR. The team has decided against it.
- Do not change the wire format of `POST /v1/orders` without coordinating with
  the Mobile and Web teams.
- Do not add new dependencies without a PR description that justifies them.

## 5. Test data

- Integration tests use Testcontainers. The connection string is
  `Host=localhost;Port=5432;Database=orders_test;Username=test;Password=test`.
- Reset between tests with `Respawn` — not by truncating tables by hand.

## 6. Owners

- Orders domain: `@sarah.lee` and `@diego.martinez`.
- Payments integration: `@priya.shah`.
- CI / build: `@alex.kim`.
