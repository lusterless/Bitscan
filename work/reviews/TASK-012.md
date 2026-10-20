# TASK-012 REVIEW: start-up configuration loader (serve and db profiles)

Reviewer: reviewer. Date: 2026-10-20. REQ-019. Spec: TS §8.6 L1302-1315, TS §8.7 L1345/L1362-1371/L1414-1416/L1447-1449, TS §5.3 (TLS only), TS §8.1 "Secrets in config", TS §8.4 (no secrets in logs); `.claude/rules/manager/config-and-cli.md`; decisions #45 (sslmode set, all three DSNs) and the 2026-10-20 TLS-file ruling; #24 open. Inputs: `work/plans/TASK-012.md`, `work/reports/TASK-012-impl.md` (revisions 1 and 2), `work/reports/TASK-012-test.md` (PASS, revision 2), `tests/m1/report.md` CHK-M1-010 to -025.

Verdict: APPROVED

Revision 2. One approval is enough here (TS §8.2 L1268): config loading is not importer, auth, agent or runner code.

## What was checked (my own probes, `manager/.venv`, throwaway files)

- **Scope:** `config/__init__.py` (15 lines) and `config/startup.py` (194 lines). The interface is exactly the plan's.
- **(a) No secret reaches any output.** I put a canary password in every DSN file and the vault-token file.
  - Paths covered:
    - a valid config;
    - malformed DSNs: bad IPv6 URI, unterminated quote, NUL, bad percent-encoding, unknown keyword;
    - an oversize file, a non-UTF-8 file, a directory path;
    - no sslmode, and an oversize token file.
  - On every path, the canary is absent from `str`, `repr`, `traceback.format_exception` and `TracebackException(capture_locals=True)`, and from captured stdout, stderr and logs.
  - `__cause__` and `__context__` are `None`.
  - DSNs and the token are `SecretStr`.
- **(b) The sslmode rule cannot be bypassed** (#45, all three DSNs).
  - Refused:
    - `PGSSLMODE=require` with no sslmode in the DSN, and `service=` alone;
    - `REQUIRE`, and an `SSLMODE=` key;
    - duplicated keys, or duplicated URI parameters, with `disable` last;
    - percent-encoded `disable`;
    - sslmode inside a quoted password, or in a URI `#fragment`;
    - `' require'`, `prefer` and `allow`.
  - Accepted, matching libpq's effective value:
    - URI or keyword `require`, `verify-ca` and `verify-full`;
    - percent-encoded `require`;
    - `service=… sslmode=verify-ca`;
    - the deprecated `requiressl=1`, which `conninfo_to_dict` resolves to `sslmode=require` (`requiressl=1 sslmode=disable` resolves to `disable` and is refused).
  - The retention and migrate DSNs get the same check.
- **(c) Opaque #24 values are not contacted.** With `socket.connect`, `getaddrinfo` and `create_connection` patched to raise, no socket call is made. `BITSCAN_VAULT_ADDR`, `BITSCAN_TOTP_KEY_REF` and `BITSCAN_AUDIT_SINK` are kept as non-empty strings. psycopg is imported only inside the DSN check.
- **(d) Ruling on the two choices not in the spec: keep both.**
  - **NUL refusal (`startup.py`, `_check_dsn`).** libpq reads a C string and stops at the first NUL. Without the refusal, the string that is checked and the string libpq connects with could differ. Refusing it is part of enforcing #45, not new behaviour.
  - **64 KiB cap on secret files.** This is validation at a real input boundary. systemd credentials allow up to 1 MiB, while a real DSN or token is under 1 KiB. It changes nothing for a valid deployment, the error names the variable, and it is documented in the impl report.
- **(e) Imports:** no `re`, `xml`, `lxml`, logging or network imports, and no SQL. ruff, ruff format and `mypy --strict` (22 files) are clean.
- **Revision 1 (my pre-review should-fix, REQ-019 (11)):**
  - `len(port) <= 5` now comes before `int(port)`;
  - a 5000-digit port and `99999` give `ConfigError: BITSCAN_LISTEN must be host:port …`;
  - `00080` parses as 80 (harmless).
- **Revision 2 (lead ruling, REQ-019 (3)):** `readable_file` refuses a TLS cert or key file that is empty (`stat().st_size == 0`, "file is empty") or missing, unreadable or a directory ("missing or unreadable"). It still never reads the content.
- **Tests:** `manager/tests/test_config.py` has 152 cases, all passing, including the canary checks. They were written from REQ-019 before the code was read (test report).

## Findings

1. **nit, for #24.** `audit_sink` and `vault_addr` are plain `str` fields, so they appear in `repr(ServeConfig)`. If #24 puts credentials into the sink URL or the vault address, make those fields `SecretStr` then.
2. **note (tester).** ruff S608 flags only SQL strings it recognises. Review stays the control for SQL text in later tasks.
