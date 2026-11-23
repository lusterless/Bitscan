package loops

import (
	"regexp"
	"strconv"
	"strings"
)

// The ClusterMAX report as cmax-helper returns it (TS §3.8): one verdict
// line per check, then its indented text.
var (
	cmaxVerdict = regexp.MustCompile(`^(PASS|FAIL|WARNING|SKIPPED|INFO)\s+.*\[([A-Za-z0-9_.-]+)\]\s*$`)
	cmaxError   = regexp.MustCompile(`(?m)^cmax: error: .*$`)
	// A ClusterMAX SKIPPED is "not applicable" (owner decision): shown as n/a.
	cmaxToken = map[string]string{"PASS": "PASS", "FAIL": "FAIL", "WARNING": "WARNING", "SKIPPED": "n/a", "INFO": "PASS"}
)

// cmaxReply caps one check's text, in characters.
const cmaxReply = 4000

// parseCmaxChecks returns every check of the report as
// "<VERDICT> observed=<value>" followed by its own text (description,
// Reproduce, Recommendation; References are left out).
func parseCmaxChecks(report string) map[string]string {
	lines := strings.Split(report, "\n")
	out := map[string]string{}
	for i, line := range lines {
		m := cmaxVerdict.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		if _, dup := out[m[2]]; dup {
			continue
		}
		observed, details, inRefs := "", []string{}, false
		for _, detail := range lines[i+1:] {
			if cmaxVerdict.MatchString(detail) || (detail != "" && !strings.HasPrefix(detail, " ")) {
				break
			}
			s := strings.TrimSpace(detail)
			switch {
			case s == "":
				continue
			case strings.HasPrefix(s, "References:"):
				inRefs = true
				continue
			case inRefs && strings.HasPrefix(s, "["):
				continue
			}
			inRefs = false
			if v, ok := strings.CutPrefix(s, "Observed:"); ok && observed == "" {
				observed = strings.TrimSpace(v)
				continue
			}
			details = append(details, s)
		}
		reply := cmaxToken[m[1]] + " observed=" + observed
		if len(details) > 0 {
			reply += "\n" + strings.Join(details, "\n")
		}
		out[m[2]] = capRunes(reply, cmaxReply)
	}
	return out
}

// parseCmaxHeader is the target block cmax prints before it starts.
func parseCmaxHeader(report string) string {
	var block []string
	started := false
	for _, line := range strings.Split(report, "\n") {
		if strings.HasPrefix(line, "# ClusterMAX audit target") {
			started = true
			continue
		}
		if started {
			if !strings.HasPrefix(line, "  ") {
				break
			}
			block = append(block, strings.TrimSpace(line))
		}
	}
	if len(block) == 0 {
		return "MISSING no target block in the report"
	}
	return capRunes(strings.Join(block, "; "), cmaxReply)
}

// cmaxErrorLine is the run's error: the "cmax: error:" line of its log, or
// the exit code.
func cmaxErrorLine(log string, exitCode int64) string {
	if m := cmaxError.FindString(log); m != "" {
		return m
	}
	return "cmax exited " + strconv.FormatInt(exitCode, 10)
}

func capRunes(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}
