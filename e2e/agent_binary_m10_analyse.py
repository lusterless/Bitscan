"""Checks for one scenario of e2e/agent_binary_m10.sh (tester-m10c).

Usage: python3 -I agent_binary_m10_analyse.py <scenario dir> <scenario name>
Prints one "PASS name" or "FAIL name" line per check.
"""

from __future__ import annotations

import json
import pathlib
import sys

d, name = pathlib.Path(sys.argv[1]), sys.argv[2]
reqs = [json.loads(line) for line in (d / "requests.jsonl").read_text().splitlines() if line.strip()]
runner = [json.loads(line) for line in (d / "runner.jsonl").read_text().splitlines() if line.strip()]
jobs = json.loads((d / "jobs.json").read_text())
comp = jobs[0]
pids = [p["plugin_uuid"] for p in comp["plugins"]]
out: dict[str, bool] = {}
note: list[str] = []


def results(status: int | None = 200) -> list[dict]:
    return [r for r in reqs if r["op"] == "results" and (status is None or r["status"] == status)]


def body(r: dict) -> dict:
    return json.loads(r["body"])


logs = (d / "stdout").read_text(errors="replace") + (d / "stderr").read_text(errors="replace")
out["no_canary_in_agent_output"] = all(c not in logs for c in ("CANARY", "/etc/shadow", "bsa_", "bse_"))
state_text = ""
for p in (d / "state").rglob("*"):
    if p.is_file():
        state_text += p.read_text(errors="replace")
out["no_command_or_pattern_in_state"] = all(c not in state_text for c in ("EXECCANARY", "PATTERNCANARY", "/etc/shadow"))
out["every_results_post_gzip"] = all(r["content_encoding"].lower() == "gzip" for r in results(None))
requests_seen = [e for e in runner if e["event"] == "request"]
hb = [body(r) for r in reqs if r["op"] == "heartbeat"]

if name in ("e2e", "invheld", "absent"):
    out["runner_contact_as_expected"] = len(requests_seen) == (0 if name == "absent" else 1)

if name == "e2e":
    posts = [body(r) for r in results()]
    out["start_notice_first"] = bool(posts) and posts[0] == {"results": [], "final": False}
    out["final_is_last_and_once"] = bool(posts) and posts[-1]["final"] and sum(p["final"] for p in posts) == 1
    got = [it["plugin_uuid"] for p in posts for it in p["results"]]
    out["each_plugin_once"] = sorted(got) == sorted(pids)
    out["items_are_the_runner_results"] = all(it["stdout"] == "out M10RUNNERCANARY" and it["error"] is None for p in posts for it in p["results"])
    req = requests_seen[0]["request"] if requests_seen else {}
    sent = dict(req.get("job", {}))
    want = dict(comp)
    sent.pop("pickup_by", None), want.pop("pickup_by", None)
    out["runner_got_the_whole_job"] = req.get("v") == 1 and sent == want
    out["runner_mpp_is_the_heartbeat_value"] = req.get("max_parallel_plugins") == 2
    out["done_reached"] = any(e["event"] == "done" for e in runner)

if name == "sigterm":
    t2 = float((d / "phase2.t").read_text())
    man = json.loads((d / "manifest-after-term.json").read_text())
    out["manifest_unfinished_after_sigterm"] = man.get("finished") is False
    items = [x for x in (d / "spool-after-term.txt").read_text().split() if x.endswith(".json") and x != "job.json"]
    out["one_item_spooled_at_sigterm"] = len(items) == 1
    out["runner_saw_the_agent_close"] = any(e["event"] == "agent closed" and e["t"] < t2 for e in runner)
    out["no_final_batch_ever"] = not any(body(r)["final"] for r in results(None))
    after = [it["plugin_uuid"] for r in results() if r["t"] > t2 for it in body(r)["results"]]
    out["spooled_item_posted_after_restart"] = after == [pids[0]]
    out["job_not_resent_to_the_restarted_runner"] = len(requests_seen) == 1
    out["no_unavailable_fill_for_the_stopped_job"] = not any(it.get("error") for r in results(None) for it in body(r)["results"])

if name == "nospool":
    out["no_results_post"] = not results(None)
    out["runner_never_contacted"] = not any(e["event"] == "connection" for e in runner)
    inv = [r for r in reqs if r["op"] == "inventory"]
    out["inventory_uploaded"] = any(r["query"] == "job_id=" + jobs[1]["job_id"] for r in inv)
    out["first_heartbeat_last_error"] = bool(hb) and hb[0].get("last_error") == "spool: not opened; compliance jobs refused"
    out["log_says_spool_not_opened"] = "the result spool could not be opened" in logs
    out["compliance_job_refused"] = "no compliance handler" in logs and comp["job_id"] in logs
    sp = d / "state" / "spool"
    out["spool_file_unchanged"] = sp.is_file() and sp.read_text() == "not a directory\n"

if name == "invheld":
    inv = [r for r in reqs if r["op"] == "inventory"]
    req_t = requests_seen[0]["t"] if requests_seen else 1e18
    closed = [e["t"] for e in runner if e["event"] == "agent closed"]
    out["inventory_uploaded_while_compliance_held"] = bool(inv) and inv[0]["t"] > req_t and (not closed or inv[0]["t"] < closed[0])
    out["inventory_for_the_job"] = bool(inv) and inv[0]["query"] == "job_id=" + jobs[1]["job_id"]

if name == "absent":
    posts = [body(r) for r in results()]
    items = [it for p in posts for it in p["results"]]
    out["final_posted"] = bool(posts) and posts[-1]["final"]
    out["every_plugin_runner_unavailable"] = sorted(i["plugin_uuid"] for i in items) == sorted(pids) and all(
        i["error"] == "runner_unavailable" and i["exit_code"] is None and i["stdout"] == "" and i["stderr"] == "" for i in items)
    out["inventory_uploaded"] = any(r["op"] == "inventory" for r in reqs)
    out["log_says_runner_unavailable"] = "runner is unavailable" in logs

if name == "dropped":
    out["first_heartbeat_last_error"] = bool(hb) and hb[0].get("last_error") == "spool: results dropped at start (unreadable)"
    out["log_names_the_dropped_job"] = "spooled results dropped at start" in logs and "d9000000-0000-4000-8000-000000000999" in logs
    out["unreadable_job_removed"] = not (d / "state" / "spool" / "d9000000-0000-4000-8000-000000000999").exists()
    out["compliance_still_runs"] = any(body(r)["final"] for r in results())

if name == "overflow":
    sizes = [int(x) for x in (d / "spoolsize.txt").read_text().split() if x.strip()]
    note.append("max spool bytes sampled %d (bound 1048576), samples %d" % (max(sizes or [0]), len(sizes)))
    out["spool_never_over_1MiB"] = bool(sizes) and max(sizes) <= 1048576
    ok = [it for r in results() for it in body(r)["results"]]
    seen = [i["plugin_uuid"] for i in ok]
    out["every_plugin_posted_once"] = sorted(seen) == sorted(pids)
    markers = {i["plugin_uuid"] for i in ok if i["error"] == "spool_overflow"}
    whole = {i["plugin_uuid"] for i in ok if i["error"] is None}
    k = len(markers)
    note.append("markers %d, whole %d" % (k, len(whole)))
    out["oldest_are_markers_newest_whole"] = 0 < k < len(pids) and markers == set(pids[:k]) and whole == set(pids[k:])
    out["markers_have_the_marker_shape"] = all(
        i["exit_code"] is None and i["stdout"] == "" and i["stderr"] == "" and not i["timed_out"] and not i["truncated"] for i in ok if i["error"])
    first503 = next((body(r)["results"] for r in results(503) if body(r)["results"]), [])
    note.append("first 503 batch: %d items %s" % (len(first503), [i["plugin_uuid"][-3:] for i in first503]))
    out["a_batch_was_in_flight_during_the_outage"] = bool(first503)
    out["the_in_flight_batch_became_markers"] = bool(first503) and {i["plugin_uuid"] for i in first503} <= markers
    out["final_posted"] = any(body(r)["final"] for r in results())
    bodies503 = [r["body"] for r in results(503)]
    note.append("503 answers %d, distinct bodies %d" % (len(bodies503), len(set(bodies503))))

for k_, v in out.items():
    print(("PASS " if v else "FAIL ") + k_)
for n in note:
    print("NOTE " + n)
