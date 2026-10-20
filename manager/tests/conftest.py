"""PostgreSQL 16 Testcontainers harness (TASK-003, REQ-009; TS §8.3 Integration).

Tests marked ``pg`` get ``pg_connect``, a factory for superuser connections to a
throwaway PostgreSQL 16 container built from ``tests/postgres/Dockerfile``
(``pg_trgm``, ``pgcrypto``, ``debversion``). The superuser is only for the TS §5.2
Bootstrap step that M1 adds; tests never run as a superuser after it.

Without Docker the ``pg`` tests are skipped with "not run: Docker unavailable",
unless ``CI=true``, where the same condition fails the run (PD-15).
"""

import os
import secrets
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

IMAGE_TAG = "bitscan-test-postgres:16"
BUILD_CONTEXT = Path(__file__).resolve().parent / "postgres"
NOT_RUN = "not run: Docker unavailable"

Connect = Callable[[], psycopg.Connection[Any]]


def _docker_problem() -> str | None:
    try:
        from testcontainers.core.docker_client import DockerClient

        DockerClient().client.ping()
    except Exception as exc:  # any failure to reach the daemon means "no Docker"
        return f"{type(exc).__name__}: {exc}"
    return None


@pytest.hookimpl(trylast=True)  # after -m / -k deselection
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    pg_items = [item for item in items if item.get_closest_marker("pg")]
    if not pg_items:
        return
    problem = _docker_problem()
    if problem is None:
        return
    if os.environ.get("CI", "").lower() == "true":
        pytest.exit(f"{NOT_RUN} and CI=true: PostgreSQL tests must run ({problem})", 1)
    for item in pg_items:
        item.add_marker(pytest.mark.skip(reason=NOT_RUN))


@pytest.fixture(scope="session")
def pg_connect() -> Iterator[Connect]:
    from testcontainers.community.postgres import PostgresContainer
    from testcontainers.core.image import DockerImage

    password = secrets.token_urlsafe(24)
    with (
        DockerImage(path=BUILD_CONTEXT, tag=IMAGE_TAG, clean_up=False) as image,
        PostgresContainer(
            image=str(image),
            username="postgres",
            password=password,
            dbname="postgres",
            driver=None,
        ) as pg,
    ):
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)

        def connect() -> psycopg.Connection[Any]:
            return psycopg.connect(
                host=host,
                port=port,
                user="postgres",
                password=password,
                dbname="postgres",
                autocommit=True,
            )

        yield connect
