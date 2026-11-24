# ClusterMAX scanner role

The ClusterMAX scanner helper (TS §3.8). When an admin starts a ClusterMAX
scan, `bitscan-agent` on the chosen scanner host asks it to run
`cmax audit -vvv -y` as root, with an optional target, an optional kubeconfig
(passed as a sealed memfd) and allow-listed variables, and gets the report,
run log, `audit.out` and `audit.values.json` back. It is part of the
`bitscan-agent` package and on by default on every agent host.

| Path | What |
|---|---|
| `src/cmax_helper.py` | `/usr/sbin/cmax-helper`: root, socket-activated, accepts only uid `bitscan`, runs the one fixed audit and returns its files |
| `systemd/` | `cmax-helper.socket` and `cmax-helper.service`, verbatim from TS §3.8 |
| `packaging/` | `stage.sh`, the hash-pinned `requirements.txt` and the `cmax` entry point |
| `tools/gen_clustermax_bit.py` | Generates `bits/samples/clustermax-0.3.0.bit` (83 plugins: header, status and the 81 checks; each Execute is `cmax-check <id>` and is never run) from `tools/clustermax-0.3.0-checks.txt`; `tools/plugin-ids.json` keeps the plugin ids stable |
| `tests/` | Helper tests; `fixtures/report-vm.txt` is a real ClusterMAX 0.3.0 report |

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

With `-y` and target `auto`, ClusterMAX detects standalone, Slurm or
Kubernetes on the scanner host. Standalone audits only that host; Slurm and
Kubernetes audits reach the whole cluster from it.

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
