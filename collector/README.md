# ClusterMAX collector

The ClusterMAX collector helper (TS §3.8). It lets a Bitscan scan of the
ClusterMAX policy run `cmax audit -vvv -y` as root on a host, while
`bitscan-agent` and `bitscan-runner` keep their privileges. Since the owner
decision of 2026-11-15 it is part of the `bitscan-agent` package and on by
default on every agent host; there is no separate collector package.

| Path | What |
|---|---|
| `src/cmax_helper.py` | `/usr/sbin/cmax-helper`: root, socket-activated, runs the one fixed audit, keeps the report in memory |
| `src/cmax_trigger.py` | `/usr/bin/cmax-trigger`: the client plugins call (`collect`, `get <check-id>`, `get header`, `get status`) |
| `systemd/` | `cmax-helper.socket` and `cmax-helper.service`, verbatim from TS §3.8 |
| `packaging/` | `stage.sh`, the hash-pinned `requirements.txt` and the `cmax` entry point |
| `tools/gen_clustermax_bit.py` | Generates `bits/samples/clustermax-0.3.0.bit` (84 plugins) from `tools/clustermax-0.3.0-checks.txt`; `tools/plugin-ids.json` keeps the plugin ids stable |
| `tests/` | Helper and client tests; `fixtures/report-vm.txt` is a real ClusterMAX 0.3.0 report |

## Build

`deploy/debian/build-deb.sh` runs `collector/packaging/stage.sh`, which
fetches `lusterless/clustermax` at `f849f46`, checks the commit and the
version (0.3.0), installs the hash-pinned pure-Python dependencies, and stages
the files the agent package installs. Two builds give the same `.deb`. The
package needs Python 3.10 or later.

## On a host

`postinst` enables and starts `cmax-helper.socket` on first install. The
manager never installs, enables or configures the helper. To turn it off on a
host (an upgrade keeps it off):

```bash
sudo systemctl disable --now cmax-helper.socket
```

To turn it on again:

```bash
sudo systemctl enable --now cmax-helper.socket
```

With `-y`, ClusterMAX auto-detects standalone, Slurm or Kubernetes on each
host, so target the policy with a dedicated tag.

## Tests

```bash
python3 -m pytest -q collector/tests
```

## Upgrading ClusterMAX

1. Review the upstream diff from the pinned commit.
2. Update `CLUSTERMAX_COMMIT` and `CLUSTERMAX_VERSION` in
   `packaging/stage.sh` (and the pinned commit in
   `deploy/tests/test_build_deb.sh`), and the hashes in
   `packaging/requirements.txt` if the dependencies change.
3. Save the new check list (`cmax audit --show -vvv`) as
   `tools/clustermax-<version>-checks.txt`, update the paths and the version
   check in `tools/gen_clustermax_bit.py`, and regenerate the `.bit` file.
