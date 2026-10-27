#!/bin/bash
# Agent idle cost on a real host (TP-M6-13, CHK-M6-300; REQ-149; #95 method,
# work/plans/M6-e2e.md section 5). Recorded against TS 3.3 L216 (< 0.1 % CPU,
# < 30 MB RSS); no gate (testing.md own question).
#
# Runs ON the VM as root (copied there and started over ssh):
#   sudo bash idle_cost.sh SECONDS [INTERVAL]
# Prints one JSON object on stdout. Touches nothing: it only reads /proc and
# `systemctl show`. The caller makes sure nothing else happens on the host
# meanwhile (no dpkg change, no API call that touches it).
set -u
export LC_ALL=C
DUR=${1:?seconds}; STEP=${2:-10}
case "$DUR$STEP" in *[!0-9]*) echo "SECONDS and INTERVAL must be integers" >&2; exit 2 ;; esac
[ "$(id -u)" = 0 ] || { echo "run as root (reads the agent's /proc entries)" >&2; exit 2; }
pid=$(systemctl show -p MainPID --value bitscan-agent.service)
[ -n "$pid" ] && [ "$pid" != 0 ] || { echo "bitscan-agent.service is not running" >&2; exit 1; }
inv0=$(systemctl show -p InvocationID --value bitscan-agent.service)
tck=$(getconf CLK_TCK); ncpu=$(nproc)
ticks() { awk '{print $14 + $15}' "/proc/$pid/stat"; }   # utime + stime, own threads
rss_kb() { awk '/^VmRSS:/ {print $2}' "/proc/$pid/status"; }
t0=$(date +%s.%N); c0=$(ticks); maxrss=$(rss_kb); samples=1; sum=$maxrss
memcur_max=$(systemctl show -p MemoryCurrent --value bitscan-agent.service)
end=$(( $(date +%s) + DUR ))
while [ "$(date +%s)" -lt "$end" ]; do
    sleep "$STEP"
    [ -r "/proc/$pid/status" ] || { echo "{\"error\": \"bitscan-agent (pid $pid) exited during the measurement\"}"; exit 1; }
    r=$(rss_kb); samples=$((samples + 1)); sum=$((sum + r))
    [ "$r" -gt "$maxrss" ] && maxrss=$r
    m=$(systemctl show -p MemoryCurrent --value bitscan-agent.service)
    case "$m" in ''|*[!0-9]*) ;; *) [ "$m" -gt "${memcur_max:-0}" ] 2>/dev/null && memcur_max=$m ;; esac
done
t1=$(date +%s.%N); c1=$(ticks)
inv1=$(systemctl show -p InvocationID --value bitscan-agent.service)
awk -v t0="$t0" -v t1="$t1" -v c0="$c0" -v c1="$c1" -v tck="$tck" -v n="$ncpu" \
    -v maxrss="$maxrss" -v avg="$((sum / samples))" -v samples="$samples" -v mc="$memcur_max" \
    -v pid="$pid" -v same="$([ "$inv0" = "$inv1" ] && echo true || echo false)" 'BEGIN {
    dt = t1 - t0; dticks = c1 - c0
    one = dticks / (tck * dt) * 100
    printf "{\"pid\": %d, \"same_invocation\": %s, \"seconds\": %.1f, \"cpu_ticks\": %d, \"clk_tck\": %d, \"vcpus\": %d,", pid, same, dt, dticks, tck, n
    printf " \"cpu_pct_one_cpu\": %.4f, \"cpu_pct_vm\": %.4f, \"vmrss_max_kb\": %d, \"vmrss_avg_kb\": %d, \"rss_samples\": %d,", one, one / n, maxrss, avg, samples
    printf " \"memory_current_max_bytes\": \"%s\", \"target\": \"< 0.1 %% CPU, < 30 MB RSS (TS 3.3 L216)\",", mc
    printf " \"cpu_within_target\": %s, \"rss_within_target\": %s}\n", (one < 0.1 ? "true" : "false"), (maxrss < 30 * 1024 ? "true" : "false")
}'
