---
paths:
  - "manager/**/services/importer/**"
  - "bits/**"
  - "**/*.bit"
---

# `.bit` file format, validation and BIT102

Format, element order and validation codes: SR §1–§4. A `.bit` file is one UTF-8 XML document holding exactly one Policy, one Family and its Plugins, mapped one-to-one onto `policy`, `family`, `plugin` and `policy_plugin`.

## Format (SR §2)

- One `<Policy formatVersion="1.0">` root, with children in this order: `PolicyName`, `PolicyDescription`, `PolicyStatus`, `Family` (holding `FamilyName`), `PluginsGroups`. Each `Plugin` has `PluginName`, `PluginDescription`, `PluginId`, `Execute` (CDATA, optional `timeout` 1–600, default 60), `Operator`, `ExpectedResult` (SR §2).
- Only canonical element names are accepted, case-sensitive; the spaced or mis-cased sample tags are not (TS §1.4). Every element is required unless marked optional, and occurs once except `Plugin` (1–5,000, document order = display order).
- Exactly one `<Family>` per file; a second `Family` fails BIT002 (each required element once, SR §4.1). TS §8.5 lists this as an assumption ("Can one `.bit` file hold more than one `<Family>`? This spec assumes one."): implement one and ask before relaxing it (`work/open-questions.md` #10).
- `<PolicyName>` is the profile name and natural key, 1–128 chars after trimming, unique across all files. File names are never used as names.
- Limits: `PolicyDescription` 0–4,000; `FamilyName` 1–128; `PluginName` 1–255; `PluginDescription` 0–4,000; `ExpectedResult` 0–4,000, trimmed; `Execute` 1–16,384 after trimming. Lengths are in characters, as `VARCHAR(n)` counts them (SR §2, TS §5.2).
- **Decided** (`work/open-questions.md` #17, owner-approved): every text element is trimmed of leading and trailing space, tab, CR and LF before its length and empty checks.
- `@formatVersion` is optional, only `1.0`. `PolicyStatus` and `Operator` are case-insensitive on input and stored lowercase.
- `PluginId` is an RFC 4122 UUID, lowercase, owned by exactly one policy; policies sharing a check use separate ids.
- **Decided** (`work/open-questions.md` #109, owner-approved): an uppercase `PluginId` is rejected with BIT004. The accepted form is exactly `8-4-4-4-12` lowercase hexadecimal; braces, `urn:uuid:` and unhyphenated forms are BIT004 too, and version and variant bits are not checked.
- `ExpectedResult` is empty only with `empty`/`not_empty`, a number for numeric operators, and a valid RE2 pattern for `regex`/`not_regex`.
- Displayed plugin name: `<FamilyName> - <PluginName>`, read from the `v_plugin` view (`display_name`, not stored in the catalog, TS §5.2); each `scan_result` keeps the run-time name in `plugin_name_snap` (TS §5.2).
- `Execute` is trimmed of leading and trailing whitespace before hashing and storing (`execute_sha256`).
- `control_ref` is the leading `\d+(\.\d+)*` of `PluginName`, NULL if longer than 32 characters.

## Validation (SR §4)

- A file is imported whole or rejected whole. Report every failing rule (not just the first), each with its line number, in `bit_import.errors`. BIT001 and BIT002 run first; if either fails, skip the content rules. Severity is per rule, not by number range.
- Reject: BIT001 (well-formed UTF-8 XML, ≤ 5 MB, no DTD or external entities), BIT002 (canonical names, each required element once, in order), BIT003 (status), BIT004 (UUID), BIT005 (unique `PluginId` in the file), BIT007, BIT008 (`Execute` empty or > 16,384), BIT010 (operator), BIT011 (`ExpectedResult` missing), BIT012 (numeric operator, non-numeric expected), BIT013 (invalid RE2 pattern, checked with RE2, not Python `re`), BIT014 (empty/non-empty mismatch), BIT015, BIT016 (`@formatVersion` not `1.0`), BIT017 (any other SR §2 limit, `@timeout` outside 1–600, more than 5,000 plugins), BIT102. Warn: BIT101 (no leading control reference), BIT103 (control reference over 32 chars).
- **Decided** (`work/open-questions.md` #16, owner-approved): an empty `<PluginsGroups/>` is BIT002, and a non-integer `@timeout` (for example `30s` or `1.5`) is BIT017.
- BIT007: `PolicyName` already imported from a different server-folder file that still exists. If the old file is gone, the policy moves to the new file (audit-logged); a policy in `uploaded/` moves to the server folder. It never applies to uploads.
- **Decided** (`work/open-questions.md` #15, owner-approved): when two new server-folder files share a `PolicyName`, the one whose file name sorts first byte by byte is imported, and the other gets BIT007.
- BIT015: `PluginId` already owned by a different policy that is not deleted and still lists it. Otherwise the importing policy claims it.
- Codes BIT006, BIT009 and BIT018–BIT020 are retired; never reuse them.
- **Decided** (`work/open-questions.md` #2, owner-approved): a missing `<Operator>` is reported as BIT010 and a missing `<ExpectedResult>` as BIT011; BIT002 covers the other required elements.
- **Decided** (`work/open-questions.md` #110, owner-approved): warnings (BIT101, BIT103) are stored in `bit_import.errors` with the same four keys, on success and on rejection, and the import response returns them. A file with only warnings ends `success`.

## BIT102 (SR §4.2)

- Split `Execute` with a POSIX sh lexer, never with a substring search.
- Reject:
  - command words `rm`, `mv`, `cp`, `tee`, `dd`, `chmod`, `chown`, `chgrp`, `truncate`, `ln`, `install`, `mkfs`, `mount`, `umount`;
  - `sed -i`/`--in-place`; `apt`/`apt-get` `install`, `remove`, `purge`, `upgrade`, `full-upgrade`, `dist-upgrade`, `autoremove`; `dpkg` `-i`, `-r`, `-P`, `--install`, `--remove`, `--purge`, `--configure`; `systemctl` `start`, `stop`, `restart`, `reload`, `enable`, `disable`, `mask`, `unmask`, `kill`, `isolate`, `set-property`;
  - redirects (`>`, `>>`, `>|`) anywhere except `/dev/null`, `/dev/stdout`, `/dev/stderr` and `/tmp/…`;
  - `source` or `.`, `eval`, `exec`, `xargs`, and `find -exec`/`-execdir`/`-ok`/`-okdir`;
  - `sh`, `bash` or `dash` given a script file, or `-c` with `$(…)`, backticks or `<(…)`.
- **Open spec question** (`work/open-questions.md` #108; TASK-146): release 0.2.0 ships the BIT102 revision 1 rules as a named exception. The revision 2 scope (path-qualified names such as `/bin/rm`, wrappers such as `env`, `command`, `busybox` and `sudo`, `mkfs.ext4`, and command words inside `$(…)`, backticks, subshells and pipelines) still needs its test, review and second approval. Ask before changing the BIT102 rules.
- Allowed and must pass: `apt-cache policy`, `apt list --installed`, `find … -perm`, `systemctl is-enabled`, `2>/dev/null`. The SR §1.1 example and common read-only CIS commands are must-pass tests.

## Authoring rules for `bits/samples/` (SR §2.4, TS §3.7)

Fixtures in `bits/tests/` (malformed, XXE, billion-laughs, oversize) break these rules on purpose.

- Read-only: no writes outside `/tmp`, no prompts, no changes to services or packages. Print only the observed value, not a sentence. Wrap `Execute` in CDATA.
- Mount-option checks read the host view with `findmnt --task 1` or `/proc/1/mountinfo`, never plain `findmnt /tmp`.
- Live firewall and audit rules, and the loaded AppArmor profiles: `bitscan-capread nft_ruleset` / `bitscan-capread audit_rules` / `bitscan-capread apparmor_profiles` where enabled, otherwise the rule files on disk (`/etc/nftables.conf`, `/etc/audit/rules.d/`). Commands that need uid 0 fail; read config files instead.
- Never execute, source or `cd` into files or directories that non-root users can write; read them only as data.
- Rewrite CIS `xargs`/`find -exec` scripts with `find … -print` and a `while read` loop. Never compare text the redaction patterns would hide.
- **Open spec question** (`work/open-questions.md` #111): the CIS control numbers in `bits/samples/` (for example `1.3.1.1`) are unconfirmed against the benchmark copy (TS §8.5), and each sample's `PolicyDescription` says so. Ask before changing them or presenting them as confirmed.

Tests (TS §8.3): Unit (validators, one case per BIT code; BIT102 lexer with the must-pass corpus; the SR §1.1 example imports), Security (BIT102 and BIT015 rejections), Sandbox (every PR touching plugins: the full CIS plugin set passes under the sandbox and BIT102, on amd64 and arm64).
