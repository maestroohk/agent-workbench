# MySQL Profile

Loaded when the repository contains `my.cnf`, `initdb.d/`, or migrations referencing MySQL.

## Schema

- Use `utf8mb4` and `utf8mb4_0900_ai_ci` (MySQL 8) or `utf8mb4_unicode_ci` (5.7). Do not use `utf8` (3-byte).
- Primary keys: prefer surrogate auto-increment integers or UUIDs as `CHAR(36)` / `BINARY(16)`. Do not use natural keys.
- Foreign keys: declare them, do not rely on application-level enforcement.
- Timestamps: `DATETIME(6)` for high-precision, `TIMESTAMP` for timezone-aware UTC. Pick one and stay consistent.

## Migrations

- One migration per change. Forward and back migrations both committed.
- Migration names include a timestamp prefix and a short slug, e.g. `20260705_add_user_email_index.sql`.
- Migrations run inside a transaction unless the operation is DDL that cannot be transactional (in which case the migration tool handles it).
- Never drop a column in the same migration that creates its replacement.

## Indexes

- Index foreign keys. Index columns used in `WHERE`, `JOIN`, and `ORDER BY` predicates.
- Composite indexes follow the leftmost-prefix rule. Order columns by selectivity within the predicate.
- Do not over-index. Each index has a write cost.

## Queries

- Avoid `SELECT *`. Select the columns you need.
- Use parameterised queries. Do not concatenate user input into SQL.
- `EXPLAIN` queries that touch more than a few thousand rows in production data. Look for full table scans.

## Connections

- Pool connections. Do not open a new connection per query.
- Set `wait_timeout` and `interactive_timeout` to values appropriate to your pool size and workload.
- Use `READ-COMMITTED` for application-level locking unless the project documents a reason for the default.

## Backups

- Take logical backups with `mysqldump --single-transaction --routines --triggers` for InnoDB.
- Test restore. A backup that has never been restored is a hypothesis.

## Things to avoid

- Do not use MySQL reserved words as identifiers. If you must, quote them explicitly.
- Do not use `FLOAT` / `DOUBLE` for money. Use `DECIMAL(p, s)`.
- Do not store JSON blobs in `TEXT` columns when a normalised schema is appropriate. Use `JSON` if the column is genuinely free-form.
- Do not use `LOCK TABLES` in application code.
