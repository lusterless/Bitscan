# TASK-254 inputs: what `.github/workflows/e2e.yml` must provide

From tester-m11e (TP-M11-18 and -19 harnesses), 2026-11-08, for impl-deploy. The harness is `e2e/m11/` (`nightly.py`, `guests.sh`, `compat.py`, `README.md`); the rows are in `work/reports/M11-e2e-test.md`.

1. **Runner:** Linux, with `/dev/kvm` usable by root. Packages `qemu-system-x86`, `qemu-utils` and `cloud-image-utils`, plus Docker. If the hosted runner has no KVM, the nightly may fall back to the local Hyper-V VMs under the user's standing approval (decisions 2026-11-08: one VM at a time from `clean`, no token or `install.env` printed or saved).
2. **Manager host image:** build `m6b-mgrhost` from `e2e/m6/manager-host.Dockerfile`, with an `extra-ca/` context folder, empty on a hosted runner.
3. **Agent package:** `bash deploy/debian/build-deb.sh`, with its `.sha256` file beside the `.deb`.
4. **Manager release folder (REL):** the wheel, including the web UI (`npm ci --ignore-scripts && npm run build` in `web/`, then `pip wheel` as release.yml does); `bitscan-manager-<v>-requirements.txt`; the four manager units; and a `SHA256SUMS` of those six files.
5. **Cloud images:** `bash e2e/m11/guests.sh fetch IMGDIR`, which checks the release `SHA256SUMS`.
6. **N−1 (compat):**
   - `gh release download v0.1.0 --dir V010`;
   - `gh release view v0.1.0 --json body -q .body > notes.txt` for the published sums.
   
   Use a read-only token.
7. **Commands (as root):**
   - `python3 -I e2e/m11/nightly.py --tree . --rel REL --deb DEB --images IMGDIR --work W --log W.log > W.log 2>&1`
   - `python3 -I e2e/m11/compat.py --phase a` and `--phase b`, both nightly. `--phase upgrade` runs at the gate only (#153 (d)).
   - After each run: `python3 -I e2e/m11/nightly.py --check-report W/report.json`, which exits 1 on a FAIL row or a missing expected row (REQ-286).
8. **Artifacts:** `W/report.json` and `W/report.md`. They hold no secret; the sweep row checks this.
9. **Budget:** about 3 GB of memory and 20 to 25 minutes per run, about 5 of them the manager walk.
