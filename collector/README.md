# clustermax-collector

The optional ClusterMAX collector helper (TS §3.8). It lets a Bitscan scan of
the ClusterMAX policy run `cmax audit -vvv -y` as root on a host, while
`bitscan-agent` and `bitscan-runner` keep their privileges.

| Path | What |
|---|---|
| `src/cmax_helper.py` | `/usr/sbin/cmax-helper`: root, socket-activated, runs the one fixed audit, keeps the report in memory |
| `src/cmax_trigger.py` | `/usr/bin/cmax-trigger`: the client plugins call (`collect`, `get <check-id>`, `get header`, `get status`) |
| `systemd/` | `cmax-helper.socket` and `cmax-helper.service`, verbatim from TS §3.8 |
| `packaging/` | `build-deb.sh`, the hash-pinned `requirements.txt`, the `cmax` entry point and the maintainer scripts |
| `tools/gen_clustermax_bit.py` | Generates `bits/samples/clustermax-0.3.0.bit` (84 plugins) from `tools/clustermax-0.3.0-checks.txt`; `tools/plugin-ids.json` keeps the plugin ids stable |
| `tests/` | Helper and client tests; `fixtures/report-vm.txt` is a real ClusterMAX 0.3.0 report |

## Build

```bash
collector/packaging/build-deb.sh
```

It fetches `lusterless/clustermax` at `f849f46`, checks the commit and the
version (0.3.0), installs the hash-pinned dependencies, and writes
`collector/dist/clustermax-collector_0.3.0-1_all.deb` and its `.sha256`.
Two builds give the same file. The package needs `bitscan-agent` (for the
`bitscan-runner` group) and Python 3.10 or later.

## Install

Only on hosts that the ClusterMAX policy will target:

```bash
sha256sum -c clustermax-collector_0.3.0-1_all.deb.sha256
```

```bash
sudo apt install ./clustermax-collector_0.3.0-1_all.deb
```

`postinst` enables `cmax-helper.socket` only. The manager never installs,
enables or configures the helper. With `-y`, ClusterMAX auto-detects
standalone, Slurm or Kubernetes on each host, so target the policy with a
dedicated tag.

## Tests

```bash
python3 -m pytest -q collector/tests
```

## Upgrading ClusterMAX

1. Review the upstream diff from the pinned commit.
2. Update `CLUSTERMAX_COMMIT`, `CLUSTERMAX_VERSION` and `SOURCE_DATE_EPOCH`
   (the commit time) in `packaging/build-deb.sh`, and the hashes in
   `packaging/requirements.txt` if the dependencies change.
3. Save the new check list (`cmax audit --show -vvv`) as
   `tools/clustermax-<version>-checks.txt`, update the paths and the version
   check in `tools/gen_clustermax_bit.py`, and regenerate the `.bit` file.
