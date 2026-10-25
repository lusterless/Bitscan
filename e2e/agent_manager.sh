#!/bin/bash
# G41 (tests/m4/test-plan.md CHK-M4-311): the installed .deb against the real M3
# manager. Runs e2e/agent_manager.py from a copy of the tree with the manager venv.
# Usage (WSL, root, Docker): agent_manager.sh <repo> <deb-dir> <out.jsonl> [image]
set -u
REPO=${1:?repo}
DEBDIR=${2:?deb dir}
OUT=${3:?out.jsonl}
IMAGE=${4:-m4b-sysd-u24}
VENV=${VENV:-/root/venv-m4a}
W=$(mktemp -d /root/m4a-g41.XXXXXX)
trap 'rm -rf "$W"; docker ps -a --format "{{.Names}}" | grep "^m4a-g41-" | xargs -r docker rm -f >/dev/null' EXIT
tar -C "$REPO" --exclude=manager/.venv --exclude=node_modules --exclude=__pycache__ --exclude=.git --exclude=./agent --exclude=./web -cf - manager e2e docs | tar -C "$W" -xf -
cd "$W/manager" && "$VENV/bin/python" -m pip install -q --no-deps --no-build-isolation -e . >/dev/null || exit 2
export CI=true PYTHONPATH="$W/manager" PATH="$VENV/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
	SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt BSTEST_RUN_LABEL=${BSTEST_RUN_LABEL:-m4a-g41} \
	RYUK_CONTAINER_IMAGE=testcontainers/ryuk:0.8.1@sha256:bf3f74a47dee0acda89aba4b2fc9c7fdcf994a084db02a2d06566f07baae022e
sha256sum "$DEBDIR"/bitscan-agent_*_amd64.deb
cd "$W/manager" && timeout 3600 "$VENV/bin/python" "$W/e2e/agent_manager.py" --deb "$DEBDIR" --out "$OUT" --image "$IMAGE"
rc=$?
docker ps -aq --filter "label=bitscan.test-run=$BSTEST_RUN_LABEL" | xargs -r docker rm -f >/dev/null
exit $rc
