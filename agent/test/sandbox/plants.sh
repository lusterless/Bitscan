#!/bin/bash
# M10 VM-planted rows (tests/m10/test-plan.md "M10 mutation table", rows
# marked VM; REQ-262). Applies ONE planted fault to a THROWAWAY COPY of the
# source tree; the plant is never committed. Build that copy's .deb with
# deploy/debian/build-deb.sh and run run_vm.sh on a freshly restored host with
# --rows <row> --expect-red <row>: the run passes only if the row turns red.
#
# Usage: plants.sh list                 (id, row that must go red, description)
#        plants.sh apply ID COPY_DIR    (COPY_DIR must not be a git work tree)
set -euo pipefail

# id | row that must turn red | what is planted
PLANTS='
320|CHK-M10-283|sdsock peer check removed: any uid is served (runner)
325|CHK-M10-281|runner agent_id check removed
327|CHK-M10-282|runner seen set removed: a replayed job runs
329|CHK-M10-205|PR_SET_DUMPABLE not set (runner)
330|CHK-M10-206|inherited fd 3 left without close-on-exec
331|CHK-M10-211|plugin inherits the runner environment
333|CHK-M10-211|plugin stdin inherited from the runner instead of /dev/null
334|CHK-M10-211|niceness not applied
335|CHK-M10-211|I/O class not applied
336|CHK-M10-210|plugin started in supervisor (no own cgroup)
337|CHK-M10-212|cgroup.kill not written when a plugin exits
338|CHK-M10-212|subtree sweep of pids removed (a plugin moved into supervisor survives)
339|CHK-M10-212|sweep skips cgroups nested under supervisor
340|CHK-M10-214|runner starts on cgroup v1 (statfs check removed)
343|CHK-M10-212|plugin timeout not enforced
344|CHK-M10-344v|stdout truncated before redaction
371|CHK-M10-289|capread accepts a third name (id)
373|CHK-M10-217|capread passes its environment to the command
374|CHK-M10-289|capread peer check removed (sdsock: any uid served)
382|CHK-M10-220|runner logs plugin stdout at debug level
386|CHK-M10-215|capability self-check removed (with the CAP_SYS_ADMIN drop-in of the row)
388|CHK-M10-207|D-Bus policy also allows StartUnit
389|CHK-M10-204|runner unit without its InaccessiblePaths= lines
390|CHK-M10-203|runner unit without NoExecPaths=
394|CHK-M10-201|runner unit without ReadOnlyPaths=/dev/shm (2026-11-03 fix)
395|CHK-M10-203|runner unit with NoExecPaths=/ only (2026-11-03 fix undone)
391|CHK-M10-212|runner keeps running plugins after the agent closes the connection
'

if [ "${1:-}" = list ]; then
	printf '%s\n' "$PLANTS" | sed '/^$/d'
	exit 0
fi
[ "${1:-}" = apply ] || {
	echo "usage: plants.sh list | apply ID COPY_DIR" >&2
	exit 2
}
ID=${2:?id}
C=${3:?copy dir}
[ -d "$C/agent" ] || {
	echo "plants.sh: $C is not a source copy" >&2
	exit 2
}
if git -C "$C" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
	echo "plants.sh: refusing to plant in a git work tree; use a throwaway copy (git archive)" >&2
	exit 2
fi

# rep FILE OLD NEW: replace exactly one occurrence, or fail (anchor missing).
rep() {
	python3 -I - "$C/$1" "$2" "$3" <<'PY'
import sys
p, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(p, encoding="utf-8").read()
n = s.count(old)
if n != 1:
    sys.exit("PLANT ANCHOR %s: found %d times in %s" % (old[:60], n, p))
open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
PY
}

A=agent/internal
case "$ID" in
320 | 374) rep $A/sdsock/peer_linux.go 'if ok && uid == l.expectUID {' 'if ok || uid == l.expectUID {' ;;
325) rep $A/runner/checks.go 'if !strings.EqualFold(string(job.AgentID), string(own)) {' 'if false && !strings.EqualFold(string(job.AgentID), string(own)) {' ;;
327) rep $A/runner/checks.go 'if old, dup := c.seen[id]; dup {' 'if old, dup := c.seen[id]; dup && false {' ;;
329) rep agent/cmd/bitscan-runner/main.go '	if err := runner.Harden(); err != nil {' '	if err := error(nil); err != nil {' ;;
330) rep $A/sdsock/listen_linux.go '	for _, e := range entries {' '	for _, e := range entries[:0] {' ;;
331) rep $A/runner/spawn_linux.go 'Env:    []string{pathEnv},' 'Env:    append(os.Environ(), pathEnv),' ;;
333) rep $A/runner/spawn_linux.go 'Stdin:  devnull,' 'Stdin:  os.Stdin,' ;;
334) rep $A/runner/spawn_linux.go 'if err := unix.Setpriority(unix.PRIO_PROCESS, tid, niceness); err != nil {' 'if err := error(nil); err != nil {' ;;
335) rep $A/runner/spawn_linux.go 'if _, _, errno := unix.Syscall(unix.SYS_IOPRIO_SET, ioprioWhoProcess, uintptr(tid), ioprioIdle); errno != 0 {' 'if errno := unix.Errno(0); errno != 0 {' ;;
336)
	rep $A/runner/cgroup.go 'if err = c.d.FS.WriteFile(p.name+"/cgroup.procs", c.pid()); err != nil {' 'if err = error(nil); err != nil {'
	rep $A/runner/cgroup.go 'herr != nil || at != path.Join(c.d.Base, p.name) {' 'herr != nil && at != path.Join(c.d.Base, p.name) {'
	;;
337) rep $A/runner/job.go '	if err := cg.Kill(); err != nil {
		e.Log.Error("runner: plugin cgroup kill failed")' '	if err := error(nil); err != nil {
		e.Log.Error("runner: plugin cgroup kill failed")' ;;
338) rep $A/runner/sweep.go 'killed, err := c.killPids(dir)' 'killed, err := false, error(nil)' ;;
339) rep $A/runner/sweep.go 'if dir == "." && (sub == supervisor || sub == pluginsDir) {' 'if dir == supervisor || (dir == "." && (sub == supervisor || sub == pluginsDir)) {' ;;
340) rep $A/runner/hygiene_linux.go 'if magic, err := p.StatfsCgroup(); err != nil || magic != unix.CGROUP2_SUPER_MAGIC {' 'if magic, err := p.StatfsCgroup(); err != nil && magic != unix.CGROUP2_SUPER_MAGIC {' ;;
343) rep $A/runner/job.go 'timer := time.NewTimer(time.Duration(p.TimeoutS) * time.Second)' 'timer := time.NewTimer(time.Duration(p.TimeoutS) * time.Hour)' ;;
344) rep $A/redact/redact.go '	b := bytes.ToValidUTF8(data, replacement)' '	if st == Stdout && len(data) > StdoutCap {
		data = data[:StdoutCap]
	}
	b := bytes.ToValidUTF8(data, replacement)' ;;
371) rep $A/capread/capread.go '"audit_rules": {"/usr/sbin/auditctl", "-l"},' '"audit_rules": {"/usr/sbin/auditctl", "-l"},
	"id":          {"/usr/bin/id"},' ;;
373) rep $A/capread/serve_linux.go 'cmd.Env = []string{}' 'cmd.Env = os.Environ()' ;;
382) rep $A/runner/job.go '	e.Log.Info("runner: plugin done",' '	e.Log.Debug("runner: plugin output", "job_id", string(job), "stdout", string(out.Data))
	e.Log.Info("runner: plugin done",' ;;
386) rep $A/runner/hygiene_linux.go '		if set&^capDacReadSearch != 0 {' '		if set&^capDacReadSearch != 0 && false {' ;;
388) rep deploy/dbus/bitscan-runner.conf '    <allow send_destination="org.freedesktop.systemd1" send_interface="org.freedesktop.systemd1.Manager" send_member="GetUnitByPID"/>' '    <allow send_destination="org.freedesktop.systemd1" send_interface="org.freedesktop.systemd1.Manager" send_member="GetUnitByPID"/>
    <allow send_destination="org.freedesktop.systemd1" send_interface="org.freedesktop.systemd1.Manager" send_member="StartUnit"/>' ;;
389)
	rep deploy/systemd/bitscan-runner.service 'InaccessiblePaths=-/run/docker.sock -/var/run/docker.sock -/run/containerd -/run/snapd.socket -/run/snapd-snap.socket
' ''
	rep deploy/systemd/bitscan-runner.service 'InaccessiblePaths=-/run/systemd/journal/socket -/run/systemd/journal/stdout -/run/systemd/journal/syslog -/run/systemd/journal/dev-log
' ''
	;;
390) rep deploy/systemd/bitscan-runner.service 'NoExecPaths=/ /tmp /var/tmp
' '' ;;
394) rep deploy/systemd/bitscan-runner.service 'ReadOnlyPaths=/dev/shm
' '' ;;
395) rep deploy/systemd/bitscan-runner.service 'NoExecPaths=/ /tmp /var/tmp
' 'NoExecPaths=/
' ;;
391) rep $A/runner/serve.go '		_, _ = conn.Read(b[:])
		cancel()' '		_, _ = conn.Read(b[:])' ;;
*)
	echo "plants.sh: unknown plant $ID" >&2
	exit 2
	;;
esac
echo "planted $ID: $(printf '%s\n' "$PLANTS" | grep "^$ID|" | cut -d'|' -f3)"
