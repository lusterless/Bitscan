# TASK-031 IMPL report: `app_user` and `user_token` repositories

REQ: REQ-044, REQ-048, REQ-051, REQ-052. Spec: TS §5.2 L951–L979 (`user_role`, `app_user`, `user_token`, grants), TS §6.2 L1076–L1091, TS §5.3 L1050 (users never deleted); #56 (d) (case-sensitive exact username match); plans `work/plans/TASK-037.md`, `-038.md`, `-041.md`, `-042.md` (the consumers). **Two approvals (TS §8.2, auth).** No schema change.

## Files (2)

- `manager/bitscan_manager/repositories/users.py`: new, `UserRepo(conn)`, `UserRow`, `DuplicateUsername`.
- `manager/bitscan_manager/repositories/user_tokens.py`: new, `UserTokenRepo(conn)`, `TokenOwner`, `ApiTokenRow`, `KINDS`.

Size: 247 non-blank lines including docstrings (about 215 lines of code), a little over the 190 estimate. The extra lines are the setters that TASK-038 to TASK-042 need: their file lists do not include the repositories, so the setters must live here.

## Conventions

- Each repository wraps one `psycopg.Connection` and runs inside the caller's transaction. It never commits and never logs.
- Every statement is a fixed string or a `psycopg.sql` composition of fixed parts, with `%s` parameters. `ruff check` (S608 on) passes.
- Every time value is passed in as a parameter (`now`, from the TASK-025 `Clock`), never taken from the database's `now()`. This covers `created_at` on inserts too, so fake-clock tests control the idle and maximum rules and the back-off.
- `UserRow.password_hash` and `totp_secret_enc` are `repr=False`, so neither appears in a `repr`, a log line or an assertion message.
- Only the TS §5.2 grants are used: SELECT, INSERT and UPDATE on both tables. There is no DELETE. `FOR UPDATE` needs the UPDATE grant, which `bitscan_app` has on `app_user`. `ON CONFLICT DO NOTHING` needs only INSERT.

## `UserRepo`

| Method | SQL / behaviour |
| --- | --- |
| `find_by_username(username)` | exact `username = %s` (case-sensitive, #56 (d)) |
| `get(user_id)`, `get_for_update(user_id)` | by id; the second adds `FOR UPDATE` |
| `list_page(limit, after_id)` | `user_id > after_id` (or all when `None`), `ORDER BY user_id LIMIT` |
| `insert_user(username, password_hash, role, now) -> int` | `INSERT … ON CONFLICT (username) DO NOTHING RETURNING user_id`; no row → `DuplicateUsername`. The transaction is not aborted by the duplicate, so the caller can still answer 409 inside it |
| `lock_active_admins() -> list[int]` | `SELECT user_id … WHERE role = 'admin' AND NOT disabled ORDER BY user_id FOR UPDATE` (last-admin rule, TASK-042 plan; fixed lock order, so no deadlock) |
| `set_role`, `set_disabled`, `set_password_hash`, `set_totp(user_id, secret_enc, last_step)`, `clear_totp` (both TOTP columns NULL) | single-row `UPDATE`; returns `True` if a row changed |
| `claim_totp_step(user_id, step) -> bool` | `UPDATE … SET totp_last_step = step WHERE user_id = … AND (totp_last_step IS NULL OR totp_last_step < step)`. One statement, so of two concurrent callers with the same step exactly one gets `True`: the second waits on the row lock, PostgreSQL re-checks the WHERE against the committed value, and it gets 0 rows (REQ-042 (2), (3)) |
| `record_failure(user_id, now) -> int \| None` | one `UPDATE … RETURNING failed_logins`: `failed_logins = LEAST(failed_logins + 1, 1000)`, `next_login_at = now + make_interval(secs => LEAST(900, power(2, LEAST(failed_logins + 1, 11) - 1)))`. This gives 1, 2, 4, …, 512, 900, 900 s after the n-th failure (REQ-048 (3)). It is atomic under concurrent failures, because the row lock serialises them and each sees the committed count. The 1000 cap keeps the SMALLINT safe (REQ-048 (4)) |
| `reset_failures(user_id)` | `failed_logins = 0, next_login_at = NULL` |

## `UserTokenRepo`

| Method | SQL / behaviour |
| --- | --- |
| `find_by_hash(token_hash) -> TokenOwner \| None` | one `SELECT` joining `app_user`, `WHERE t.token_hash = %s` only (unique index). It returns the row whatever its state: `kind`, `totp_verified`, `expires_at`, `last_used_at`, `revoked_at`, `created_at`, plus the owner's `user_id`, `username`, `role`, `disabled` and `totp_enrolled` (`totp_secret_enc IS NOT NULL`, not the ciphertext). All accept or reject decisions belong to TASK-037 `resolve()`. The method is named `find_by_hash` rather than the plan's `find_active_token` because it does not filter |
| `insert(*, user_id, kind, token_hash, expires_at, now, name=None, totp_verified=False) -> token_id` | `kind` must be `session` or `api` (`ValueError` otherwise). `created_at = now`. The DB CHECK still refuses `api` with `totp_verified` |
| `touch(token_id, now) -> bool` | sets `last_used_at = now` only when it is NULL or more than 60 s older (the TASK-037 plan's burst rule; the idle check then has at most 60 s of slack) |
| `revoke(token_id, now) -> bool` | the presenting token (logout); only if not already revoked |
| `revoke_own_api(user_id, token_id, now) -> bool` | `… AND user_id = … AND kind = 'api' AND revoked_at IS NULL`. The result is `False` alike for an unknown id, another user's token, a session or an already-revoked token (REQ-051 (3)) |
| `revoke_for_user(user_id, kinds, now) -> int` | `kind = ANY(%s)` over a non-empty subset of `{session, api}` (`ValueError` otherwise); returns the number of tokens revoked. This is the plan's "revoke by user and kind" (`UsersRepo.revoke_tokens` in the TASK-042 plan) |
| `list_api(user_id, limit, after_id) -> list[ApiTokenRow]` | only the caller's `kind = 'api'` rows, `token_id > after_id`, `ORDER BY token_id`. The rows hold no `token_hash` |

## Checks run (Windows)

| Check | Result |
| --- | --- |
| `ruff check manager` (S608 on), `ruff format --check manager` | pass |
| `mypy --strict --config-file manager/pyproject.toml manager` | pass, 50 files |
| `cd manager && pytest --cov=bitscan_manager/services --cov-fail-under=85` | 366 passed, 181 skipped (pg), 98.15 % (repositories are outside the G5 source) |
| Any PostgreSQL run | NOT RUN: no Docker on Windows, and only the tester runs WSL. Not one statement has run against PostgreSQL yet; TP-M2-09 is the first run |

## For the tester (TP-M2-09)

- Construct the repositories as `UserRepo(conn)` and `UserTokenRepo(conn)` on a `bitscan_app` connection, inside a transaction. Commit yourself; the repositories never commit.
- Concurrent TOTP step: two connections, each `BEGIN`, `claim_totp_step(uid, s)`, commit. Exactly one gets `True`. A later `claim_totp_step(uid, s)` or `(uid, s - 1)` gets `False`.
- Back-off: 10 threads each doing `record_failure(uid, now)` and committing should end with `failed_logins = 10`. With one connection and n sequential calls, `next_login_at - now` is `min(2^(n-1), 900)` s.
- A user row needs a `password_hash`. Any string works for these tests (the Argon2id helpers are TASK-028).
- `insert_user` with an existing username raises `DuplicateUsername`, and the same transaction can still run statements afterwards.
