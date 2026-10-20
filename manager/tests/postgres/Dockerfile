# Test-only PostgreSQL 16 image for the Testcontainers harness (TASK-003, TP-M1-02).
# Official image pinned by its multi-arch index digest (PD-14 (n)); the tag is for
# readers only. pg_trgm and pgcrypto ship in contrib; debversion comes from the
# PGDG apt repository that the official image already configures; dpkg is part of
# the Debian base (TP-M1-07).
# TLS (#45, REQ-032 (5)): a throwaway self-signed key made at build time, and a
# pg_hba.conf that accepts TCP connections only over TLS (hostssl).
FROM postgres:16-bookworm@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-debversion openssl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /etc/postgresql/tls \
    && openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=localhost" \
        -keyout /etc/postgresql/tls/server.key -out /etc/postgresql/tls/server.crt \
    && printf '%s\n' \
        'local   all all              trust' \
        'hostssl all all 0.0.0.0/0    scram-sha-256' \
        'hostssl all all ::/0         scram-sha-256' \
        > /etc/postgresql/pg_hba.conf \
    && chown -R postgres:postgres /etc/postgresql \
    && chmod 600 /etc/postgresql/tls/server.key

CMD ["postgres", \
     "-c", "ssl=on", \
     "-c", "ssl_cert_file=/etc/postgresql/tls/server.crt", \
     "-c", "ssl_key_file=/etc/postgresql/tls/server.key", \
     "-c", "hba_file=/etc/postgresql/pg_hba.conf"]
