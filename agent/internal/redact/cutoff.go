package redact

import "regexp"

// The markers of default pattern 2 (TS §8.6). These two are fixed, not
// job input.
var (
	keyBegin = regexp.MustCompile(`-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----`)
	keyEnd   = regexp.MustCompile(`-----END [A-Z0-9 ]*PRIVATE KEY-----`)
)

// cutOff is the built-in rule of TS §3.5 L251, applied whatever the job's
// list holds (#133): the first BEGIN marker with no END marker starting after
// it, and everything after it to the end of the buffer, become one Marker. A
// BEGIN followed by an END is left to the patterns.
func cutOff(b []byte) []byte {
	// lastEnd is the start of the last END marker. Each search resumes one
	// byte after the previous start, so an END that overlaps the one before
	// is found too; the markers hold no assertion, so searching a sub-slice
	// is exact.
	lastEnd := -1
	for {
		loc := keyEnd.FindIndex(b[lastEnd+1:])
		if loc == nil {
			break
		}
		lastEnd += 1 + loc[0]
	}
	// A BEGIN that starts inside the last END's own trailing dashes still has
	// no END after it, so the search starts right after the END's start.
	loc := keyBegin.FindIndex(b[lastEnd+1:])
	if loc == nil {
		return b
	}
	start := lastEnd + 1 + loc[0]
	out := make([]byte, 0, start+len(Marker))
	out = append(out, b[:start]...)
	return append(out, Marker...)
}
