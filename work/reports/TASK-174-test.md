# TASK-174 TEST: PASS (G59; a targeted re-run follows TASK-146 r2 approval)

Tester: tester-m7, 2026-10-28. Low risk (data, PD-35 second look). REQ-179 (1) to (4); SR §1.1, §2.4 (script rules), §4.2; TS §3.7 L500–L502, §8.6 L1329–L1337 (default redaction patterns, read from the spec text by the test); #111; G59 (`work/tasks.md`). File under test: `bits/samples/cis-ubuntu-24.04-l1-server.bit`. It shares one batch with TASK-175 (`work/reports/TASK-175-test.md`; plan row TP-M7-27). New test file: `manager/tests/test_bits_samples_pg.py` (50 tests). It imports through the TASK-154 pipeline (r1) into fresh databases.

**This run used the current tree, including the untested TASK-146 r2 BIT102 files** (`bit102.py`, `bit102_wrappers.py`, `bit102_braces.py`), because that is the code the samples have to pass (lead, 2026-10-28). A targeted re-run of `tests/test_bits_samples_pg.py` follows once 146 r2 is approved.

## Runs

| Run | Command (W, fresh copy `/root/bstest-m7-t174` of the current tree, `CI=true`) | Count |
| --- | --- | --- |
| g0 (`-n 2`, label `m7t-t174`) | `pytest tests/test_bits_samples_pg.py` | **50/50 passed**, 0 failed, 0 errors, 0 skipped |
| plants | 5 data plants in throwaway copies of the samples (`/root/bstest-m7-mut-<id>`, removed after each); memory checked each time, `-n 0` below 3,000 MB | 5/5 red |
| static (L) | ruff, ruff format, `mypy --strict` (CI form) on the new file | clean |

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-300 | APP | W | g0 | PASS | G59: both samples together in one fresh catalog (manual, server files), each `success` with no Reject finding and no BIT102; every plugin is in `policy_plugin` in file order, owned by its own policy and `active`; `plugins_added` equals the file's count (neither sample claims an id from the other); 2 live policies. Names and ids are distinct across the samples (parsed with defusedxml), and every id is a lowercase 8-4-4-4-12 UUID | 2026-10-28 |
| CHK-M7-301 | APP | W | g0 | PASS | The SR §1.1 example alone in another fresh catalog: `success` with no finding; the fixture equals the spec's code block | 2026-10-28 |
| CHK-M7-302 | CODE | W | g0 | PASS | REQ-179 (3): the 24.04 sample's first `<Plugin>…</Plugin>` source text is byte-identical to the SR §1.1 code block's, read from `docs/spec/bit_Schema_Reference.md`; `PolicyName` is "CIS Ubuntu 24.04 Level 1 - Server". REQ-179 (4): `PolicyDescription` ends with the #111 note; `PolicyStatus` `enabled`; `formatVersion` 1.0; 16 plugins | 2026-10-28 |
| CHK-M7-303 | CODE | W | g0 | PASS | One test per plugin (16 rows below): `Execute` is in CDATA. There is no `xargs`, no `find -exec`/`-execdir`/`-ok`/`-okdir`, no `eval`, no `source`/`.`, no `exec`, no `cd` and no `sudo`/`doas`/`su`. No shell is given a script, and no command runs from `/tmp`, `/var/tmp`, `/dev/shm`, `/home`, `~`, `./` or `$HOME`. There is no `/proc/mounts`, `/etc/mtab` or `mount`, and every `findmnt` line has `--task 1`. No uid-0 command is used (`nft`, `auditctl`, `iptables`, `ip6tables`, `aa-status`, `apparmor_status`, `sshd -T`, `ufw status`, `sysctl -w`), and there are no prompts. The timeout is 1–600. No default redaction pattern matches the `ExpectedResult`, and the five patterns were read from TS §8.6. Text operators expect a short value, not a sentence. The scan's own patterns are shown to fire on 9 bad examples and not on the SR example | 2026-10-28 |
| CHK-M7-366 | APP | W | plant: `rm x` as a 24.04 plugin's Execute | PASS (red) | 1 failed: `test_g59_all_samples_together_in_one_fresh_catalog` (BIT102 at `Plugin[5]/Execute`) | 2026-10-28 |
| CHK-M7-366 | APP | W | plant: a 22.04 plugin id set to a 24.04 one | PASS (red) | 2 failed: G59 (24.04 gets BIT015 at `Plugin[2]/PluginId`) and `test_policy_names_and_plugin_ids_are_distinct_across_the_samples` | 2026-10-28 |
| CHK-M7-303 plants | CODE | W | plants: a `findmnt` without `--task 1`; `nft list ruleset` | PASS (red) | 1 failed each, in the matching per-plugin script-rule row | 2026-10-28 |
| CHK-M7-302 plant | CODE | W | plant: the #111 note removed | PASS (red) | 1 failed: `test_description_note_and_status` | 2026-10-28 |
| G59 after 146 r2 | APP | W | — | NOT RUN yet | Targeted re-run of `tests/test_bits_samples_pg.py` once TASK-146 r2 is approved | 2026-10-28 |

## Per-plugin script-rule rows (24.04 sample; each is `test_script_rules[cis-ubuntu-24.04-l1-server.bit:<name>]`, g0)

| # | PluginName | PluginId | Operator | Result |
| --- | --- | --- | --- | --- |
| 1 | 1.3.1.1 - Ensure AppArmor is installed | `3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48` | `equals` | PASS |
| 2 | 1.1.1.1 - Ensure cramfs kernel module is not available | `9f232f90-19f8-4b58-b886-65efaf83dd9c` | `regex` | PASS |
| 3 | 1.1.2.1.2 - Ensure nodev option set on /tmp partition | `178cee42-58a3-4f26-a6f6-01dd7671030a` | `regex` | PASS |
| 4 | 1.1.2.2.3 - Ensure nosuid option set on /dev/shm partition | `b0a43662-158b-4806-9481-4202dd531870` | `regex` | PASS |
| 5 | 1.5.1 - Ensure address space layout randomization is enabled | `43bc18fb-2a2d-4d05-b334-f6ab4fefb837` | `eq` | PASS |
| 6 | 1.5.2 - Ensure ptrace_scope is restricted | `b99dbc20-84e1-4e8a-b049-d39cba025e41` | `ge` | PASS |
| 7 | 1.5.4 - Ensure prelink is not installed | `b1d61ee2-cf1a-43ce-97b6-65bfdbbecae2` | `empty` | PASS |
| 8 | 2.2.4 - Ensure telnet client is not installed | `dfa7e395-744b-402f-84ad-585d6367eb45` | `empty` | PASS |
| 9 | 2.4.1.1 - Ensure cron daemon is enabled and active | `284bab45-0ec0-4e76-806c-fe744d4294af` | `equals` | PASS |
| 10 | 3.3.1 - Ensure ip forwarding is disabled | `5a8f31b0-afbb-455c-bee9-dd067dab4ff0` | `regex` | PASS |
| 11 | 4.1.1 - Ensure ufw is installed | `a925949c-5a85-4d67-8457-0b73f415dfb5` | `equals` | PASS |
| 12 | 5.1.1 - Ensure permissions on /etc/ssh/sshd_config are configured | `77f7a15a-4f1e-4a51-9684-75d8999c7473` | `empty` | PASS |
| 13 | 5.1.20 - Ensure sshd PermitRootLogin is disabled | `e5252af6-9d2e-4238-a553-6540e3083549` | `regex` | PASS |
| 14 | 5.4.1.1 - Ensure password expiration is configured | `142a7b43-b2d3-405e-92d2-6d334ef2f2dc` | `le` | PASS |
| 15 | 5.4.2.1 - Ensure root is the only UID 0 account | `37c25aa5-c5f2-44eb-b08e-facd1f96a8c4` | `equals` | PASS |
| 16 | 7.2.2 - Ensure /etc/shadow password fields are not empty | `d9cabf04-a21c-4bf6-904c-115768ca5d9d` | `empty` | PASS |

## Notes for the reviewer (no defect)

- The script-rule scan is a pattern check, an aid to the review and not a substitute for it. BIT102 is the lexer-based check, and it ran through the import.
- Plugin 16 reads `/etc/shadow`. That is allowed: the runner has `CAP_DAC_READ_SEARCH` (TS L500). It prints only the user names whose password field is empty, or `unreadable`, never a hash, so redaction cannot hide the compared value. Its import alert flags `shadow` (#100 (c)), as it should.
- Plugin 9 uses `systemctl is-enabled` and `is-active`, the read-only uses that SR §4.2 and the D-Bus policy allow.
