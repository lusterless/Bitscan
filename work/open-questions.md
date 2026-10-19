# Open questions for the spec owner

Logged from the 2026-10-19 workspace audit (`work/audit/`). None of these is answered yet. Do not implement the affected behaviour until the owner decides; record each decision in `work/decisions.md` and then update the matching "Open spec question" line in `.claude/rules/`.

| # | Question | Sections | Audit id | Suggested answer (not a decision) |
| --- | --- | --- | --- | --- |
| 1 | Is policy delete (`DELETE /policies/{id}`) a sensitive action? It needs a TOTP session per the route table and §4.3 but is missing from the §6.2 sensitive-action list, so it is unclear whether it is also refused during an audit-sink outage | TS §6.2, §4.3, §5.3 | S-01 | Treat it as sensitive: TOTP session, refused during an outage |
| 2 | BIT010 and BIT011 say "missing", but a missing element already fails BIT002 and the content rules are then skipped, so the "missing" halves can never fire | SR §4, §4.1 | P-10 | Report a missing `<Operator>` or `<ExpectedResult>` as BIT010 or BIT011; keep BIT002 for the other elements |
| 3 | What happens when a scan target resolves to zero agents? Both "completed" and "failed" would apply, and `POST /scans` has no stated refusal | TS §4.4, §6.4 | P-11 | Refuse with 422; skip and log a scheduled run |
| 4 | Several `agent.yaml` keys clash with fixed values elsewhere: `state_dir`, `heartbeat_seconds` (300 ± 30 s), `spool_max_mb` (max 50), `log_level` values | TS §3.6 vs §3.3, §3.5, §3.7 | P-13 | `state_dir` fixed; heartbeat fixed or clamped to 270 to 330 s; spool at most 50 MB; log levels debug, info, warn, error |
| 5 | Which authentication do `/healthz`, `/readyz` and the Prometheus metrics route use? §2.3 says every call carries a bearer token | TS §2.3, §6, §8.4 | P-14 | Health routes unauthenticated and outside `/api/v1`; metrics need an admin `bsk_` token or bind to localhost |
| 6 | How is the manager installed, and how does it serve the built web UI? | TS §8.7, §2, §6.3 | P-15 | FastAPI serves `web/dist` from the same origin; manager shipped as a Python wheel with an entry point |
| 7 | How is the initial password set for `users create-admin` and for `POST /users`? | TS §6.2 | P-16 | CLI prompts on a TTY; `POST /users` takes an initial password of at least 12 characters with a forced change at first sign-in |
| 8 | May an API token revoke its own API tokens (`DELETE /api-tokens`)? The spec bans API tokens only from creating tokens and changing TOTP | TS §6.2 | R-05 | Allowed (viewer, own tokens), as the row has no "session only" marker |
| 9 | Does `GET /policies` list deleted policies (for example with `?status=deleted`)? The spec says only that a deleted policy disappears from selection | TS §4.3, §6.2 | P-20 | Not selectable for scans; visible where old results reference it |

Smaller open items from the audit (see `work/audit/planner.md`): P-12 scan `running` threshold, P-17 vault and audit-sink wire formats, P-18 heartbeat diagnostics storage and `agent_ip_seen` writers, P-19 rejecting a re-enrolment, P-38 alerts for skipped imports, P-39 expected 429s on large jobs.

Spec-internal inconsistencies for the owner (the spec is never edited here; see `work/audit/reviewer.md` S-02 to S-10): table map omits `agent_ip_seen` and `task`; component table omits `pgcrypto`; heartbeat response described as only `job_pull_seconds` in §2.3; `spool_overflow` called a runner error; "deadline" used for `pickup_by`; `failed` definition omits the 24 h never-started and inventory cases; G6 says "group" but only tags exist; `/agent/enroll` called unauthenticated but needs a `bse_` token; BIT102 listed after BIT103.
