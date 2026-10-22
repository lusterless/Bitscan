"""bitscan-manager users create-admin | create-api-token | reset-totp
(TS §8.7 L1347, §6.2 L1081, L1089, L1090; REQ-058; #7, #47 (e), #50, #51).

Run as root on the server. The bitscan_app DSN is read from APP_DSN_FILE with
the same checks as the serve profile (TLS required); messages name the file,
never its content. A password is never taken from the command line or the
environment (#7): on a terminal it is asked twice without echo, otherwise one
line is read from stdin. Each command writes its audit entry (actor cli:root)
in its own transaction; alert counters move only after that commit. Entries
reach the audit sink through the running serve's shipper (#51).
"""

import argparse
import getpass
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pydantic import SecretStr

APP_DSN_FILE: Final = Path("/etc/bitscan/secrets/app.dsn")  # TS §8.7
ACTOR: Final = "cli:root"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bitscan-manager users")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create an admin without TOTP")
    admin.add_argument("username")
    token = sub.add_parser("create-api-token", help="print a new API token once")
    token.add_argument("username")
    token.add_argument("--name", default=None, help="label, at most 64 characters")
    token.add_argument("--days", type=int, default=None, help="lifetime, 1-365 (90)")
    reset = sub.add_parser("reset-totp", help="clear a user's TOTP, end sessions")
    reset.add_argument("username")
    return parser


def _password() -> str:
    if sys.stdin.isatty():
        first = getpass.getpass("New password: ")
        if getpass.getpass("Repeat the password: ") != first:
            raise ValueError("the two passwords differ")
        return first
    return sys.stdin.readline().removesuffix("\n").removesuffix("\r")


def _dsn(path: Path) -> "SecretStr":
    from bitscan_manager.config.startup import _Loader

    # The serve profile's checks (readable, UTF-8, at most 64 KiB, TLS sslmode).
    # The loader names its key in every message, so the key is the path.
    loader = _Loader({str(path): str(path)})
    dsn = loader.dsn_file(str(path))
    loader.finish()  # ConfigError: one line per problem, no file content
    return dsn


def _run(args: argparse.Namespace, dsn: "SecretStr", password: str | None) -> int:
    from bitscan_manager.auth.api_tokens import ApiTokenInvalid, create_api_token
    from bitscan_manager.auth.passwords import PasswordRejected
    from bitscan_manager.db.pool import AppDatabase
    from bitscan_manager.repositories.audit_log import PgAuditRepo
    from bitscan_manager.repositories.user_tokens import UserTokenRepo
    from bitscan_manager.repositories.users import UserRepo
    from bitscan_manager.runtime import SystemClock
    from bitscan_manager.services import users as service

    now = SystemClock().now()
    db = AppDatabase(dsn, min_size=1, max_size=1)
    db.open()
    failure: str | None = None
    token: str | None = None
    try:
        with db.transaction() as tx:
            users, tokens = UserRepo(tx.conn), UserTokenRepo(tx.conn)
            audit = service.TxAudit(PgAuditRepo(tx.conn), tx.on_commit)
            if args.command == "create-admin":
                service.create_admin(
                    users,
                    audit,
                    actor=ACTOR,
                    username=args.username,
                    password=password or "",
                    now=now,
                )
            else:
                user = users.find_by_username(args.username)
                if user is None or user.disabled:
                    raise service.UserRuleError(service.Rule.NOT_FOUND)
                if args.command == "create-api-token":
                    token = create_api_token(
                        tx,
                        user_id=user.user_id,
                        name=args.name,
                        days=args.days,
                        now=now,
                        actor=ACTOR,
                    ).token
                else:
                    service.reset_totp(
                        users,
                        tokens,
                        audit,
                        actor=ACTOR,
                        actor_id=None,
                        user_id=user.user_id,
                        now=now,
                    )
    except service.UserRuleError as exc:
        failure = {
            service.Rule.DUPLICATE: "the username is already taken",
            service.Rule.NOT_FOUND: "no such enabled user",
            service.Rule.INVALID_USERNAME: "usernames are 1-64 of A-Z a-z 0-9 . _ @ -",
        }.get(exc.rule, exc.rule.value)
    except (PasswordRejected, ApiTokenInvalid) as exc:
        failure = str(exc)  # names the rule only
    except Exception as exc:  # database errors: type only (no DSN, no SQL)
        failure = f"database error ({type(exc).__name__})"
    finally:
        db.close()
    if failure is not None:
        print(f"users {args.command}: {failure}", file=sys.stderr)
        return 1
    if token is not None:
        print(token)  # stdout, once, and nowhere else
    return 0


def users_main(argv: Sequence[str], *, dsn_file: Path | None = None) -> int:
    """Usage errors exit 2 before any configuration or database module loads."""
    try:
        args = _parser().parse_args(list(argv))
    except SystemExit as exc:  # usage error (2) or --help (0)
        return exc.code if isinstance(exc.code, int) else 2
    from bitscan_manager.api.request_log import configure_logging
    from bitscan_manager.config.startup import ConfigError

    # Every record goes to the JSON handler, never Python's last-resort one;
    # warnings and errors only, so a command's output stays short.
    configure_logging(level=logging.WARNING)
    try:
        dsn = _dsn(dsn_file or APP_DSN_FILE)
    except ConfigError as exc:
        for line in str(exc).splitlines():
            print(f"users {args.command}: {line}", file=sys.stderr)
        return 2
    password: str | None = None
    if args.command == "create-admin":
        try:
            password = _password()
        except (ValueError, EOFError, KeyboardInterrupt) as exc:
            print(
                f"users create-admin: password not read ({exc or type(exc).__name__})",
                file=sys.stderr,
            )
            return 1
    if password is not None:  # refuse a bad password before waiting on the database
        from bitscan_manager.auth.passwords import PasswordRejected, check_new_password

        try:
            check_new_password(password)
        except PasswordRejected as exc:
            print(f"users create-admin: {exc}", file=sys.stderr)
            return 1
    return _run(args, dsn, password)
