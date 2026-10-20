# Test-only PostgreSQL 16 image for the Testcontainers harness (TASK-003, REQ-009).
# Official image pinned by its multi-arch index digest (PD-14 (n)); the tag is for
# readers only. pg_trgm and pgcrypto ship in contrib; debversion comes from the
# PGDG apt repository that the official image already configures.
FROM postgres:16-bookworm@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-debversion \
    && rm -rf /var/lib/apt/lists/*
