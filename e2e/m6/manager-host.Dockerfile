# A fresh systemd Ubuntu 24.04 manager host for the install walk (TP-M6-03,
# CHK-M6-042; #93). Only what a minimal Ubuntu 24.04 server image already has:
# systemd as PID 1, D-Bus, sudo with an administrator account, adduser, curl,
# OpenSSL, GnuPG and the CA store. No Bitscan file, no PostgreSQL and no
# Python: the runbook installs those.
#
# Build context: a folder holding `extra-ca/` (the TLS-interception root the
# WSL host trusts, or nothing) so apt and pip work behind the proxy; it is the
# environment's root, never a Bitscan test CA, and is not committed.
#
#   docker build -t m6b-mgrhost -f e2e/m6/manager-host.Dockerfile <context>
#   docker run -d --name m6b-host --hostname bitscan-mgr --privileged \
#     --cgroupns=private --tmpfs /run --tmpfs /run/lock \
#     --add-host bitscan-mgr.test:127.0.0.1 m6b-mgrhost
#
# No port is published: the walk talks to the manager from inside the host
# (the container's own network namespace, so its 8443 is not the WSL port).
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
COPY extra-ca/ /usr/local/share/ca-certificates/
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
      systemd systemd-sysv dbus sudo adduser ca-certificates curl openssl gnupg \
      procps iproute2 less tzdata >/dev/null \
 && update-ca-certificates >/dev/null \
 && rm -rf /var/lib/apt/lists/* /usr/sbin/policy-rc.d \
 && : > /etc/machine-id \
 && useradd -m -s /bin/bash -G sudo admin \
 && echo 'admin ALL=(ALL:ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-admin \
 && chmod 0440 /etc/sudoers.d/90-admin
STOPSIGNAL SIGRTMIN+3
# On a real host systemd makes / shared at boot; inside a container it leaves
# the container manager's private propagation, and then LoadCredential= copies
# never appear in /run/credentials/<unit> (systemd 255 moves them in from a
# child namespace). Making / shared first gives the container the host
# behaviour; nothing about the units changes (CHK-M6-042 probe).
ENTRYPOINT ["/bin/sh", "-c", "mount --make-rshared / && exec /sbin/init"]
