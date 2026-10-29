# TASK-175 TEST: PASS (G59; a targeted re-run follows TASK-146 r2 approval)

Tester: tester-m7, 2026-10-28. Low risk (data, PD-35 second look). REQ-179 (1), (2), (4); #111; G59. File under test: `bits/samples/cis-ubuntu-22.04-l1-server.bit`. It shares one batch, test file and run with TASK-174. The runs, method and the note about the untested TASK-146 r2 BIT102 code are in `work/reports/TASK-174-test.md`. Test file `manager/tests/test_bits_samples_pg.py`; run g0 (W, `-n 2`): **50/50 passed**, 0 failed, 0 errors, 0 skipped.

## Report rows (tests/m7/report.md format)

| Check | Type | Where | Command | Result | Evidence | Date |
| --- | --- | --- | --- | --- | --- | --- |
| CHK-M7-300 | APP | W | g0 | PASS | Imported together with the 24.04 sample into one fresh catalog: `success`, no Reject, no BIT102, all 16 plugins its own, in order and `active`. TASK-175's own acceptance: its `PolicyName` ("CIS Ubuntu 22.04 Level 1 - Server") and all 16 plugin ids differ from TASK-174's (the two id sets are disjoint) | 2026-10-28 |
| CHK-M7-302 | CODE | W | g0 | PASS | `PolicyDescription` ends with the #111 note; `PolicyStatus` `enabled`; `formatVersion` 1.0; 16 plugins | 2026-10-28 |
| CHK-M7-303 | CODE | W | g0 | PASS | One script-rule test per plugin (16 rows below), the same rules as in TASK-174's report | 2026-10-28 |
| CHK-M7-366 | APP | W | plant: its first plugin id set to a 24.04 id | PASS (red) | 2 failed: G59 (BIT015) and the distinct-ids test | 2026-10-28 |
| CHK-M7-303 plants | CODE | W | plants: `findmnt` without `--task 1` (plugin 2); `nft list ruleset` (plugin 8) | PASS (red) | 1 failed each, in that plugin's row | 2026-10-28 |
| CHK-M7-302 plant | CODE | W | plant: the #111 note removed | PASS (red) | 1 failed: `test_description_note_and_status[cis-ubuntu-22.04-l1-server.bit]` | 2026-10-28 |
| G59 after 146 r2 | APP | W | — | NOT RUN yet | Targeted re-run once TASK-146 r2 is approved | 2026-10-28 |

## Per-plugin script-rule rows (each is `test_script_rules[cis-ubuntu-22.04-l1-server.bit:<name>]`, g0)

| # | PluginName | PluginId | Operator | Result |
| --- | --- | --- | --- | --- |
| 1 | 1.1.1.1 - Ensure mounting of cramfs filesystems is disabled | `4ad2762c-4a2e-4cc9-b2d9-aaa07e2dd004` | `regex` | PASS |
| 2 | 1.1.2.2 - Ensure nodev option set on /tmp partition | `b69d9484-b747-49e5-9e18-77286c465462` | `regex` | PASS |
| 3 | 1.5.1 - Ensure address space layout randomization (ASLR) is enabled | `d51aca51-c254-4205-b160-0652821bc7c8` | `eq` | PASS |
| 4 | 1.5.2 - Ensure prelink is not installed | `ee728f4f-4efa-4e79-a1ad-e46310bb58fe` | `empty` | PASS |
| 5 | 1.6.1.1 - Ensure AppArmor is installed | `62a0af59-300a-4530-a7ba-c5cea17b882e` | `empty` | PASS |
| 6 | 2.3.4 - Ensure telnet client is not installed | `107c56a7-2a88-4525-bd10-22df060715cc` | `empty` | PASS |
| 7 | 3.2.2 - Ensure IP forwarding is disabled | `296d3e22-0ecf-469f-9cf1-d6b54df12d60` | `regex` | PASS |
| 8 | 3.3.8 - Ensure TCP SYN Cookies is enabled | `59a56ce7-5eb1-4aa0-a078-f6761b36d69b` | `eq` | PASS |
| 9 | 3.5.1.1 - Ensure ufw is installed | `01b0f9e1-409b-4709-880f-a45e652d16a1` | `equals` | PASS |
| 10 | 5.1.1 - Ensure cron daemon is enabled and running | `9d401969-5f86-4dda-bd55-0006798cd5b7` | `equals` | PASS |
| 11 | 5.2.1 - Ensure permissions on /etc/ssh/sshd_config are configured | `54a418be-5377-4c7d-ad77-f9517dc85b72` | `empty` | PASS |
| 12 | 5.2.7 - Ensure SSH root login is disabled | `6669fc6d-e26c-4e3f-9dcc-1c8bf82f1b5f` | `regex` | PASS |
| 13 | 5.2.18 - Ensure SSH MaxAuthTries is set to 4 or less | `f3774cdb-aa44-4fbe-82c1-4661a6cf5547` | `regex` | PASS |
| 14 | 5.5.1.2 - Ensure password expiration is 365 days or less | `597aaa58-5ea8-44f5-b368-f3ea4e166add` | `le` | PASS |
| 15 | 6.1.1 - Ensure permissions on /etc/passwd are configured | `857797fb-c2a0-4f00-bc7a-50a0f213f39c` | `regex` | PASS |
| 16 | 6.2.2 - Ensure /etc/shadow password fields are not empty | `4631d4ee-b1c7-4912-99e3-f10954d4a101` | `empty` | PASS |

Note (no defect): plugin 16 reads `/etc/shadow` and prints only the user names with an empty password field, or `unreadable`. The same note applies as for TASK-174's 7.2.2.
