// Package redact turns one captured plugin stream into the text that may
// leave the runner (TS §3.5 L251; #133, #134): invalid UTF-8 replaced, the
// job's patterns applied in list order, the cut-off private-key rule, then a
// cut at a UTF-8 boundary to the stream's cap. Redaction runs before the cut,
// so a secret cut by the cap is never partly returned. Pure Go: Go's regexp
// is RE2 syntax with linear-time matching.
package redact

import (
	"bytes"
	"regexp"
	"unicode/utf8"
)

// Sizes in bytes (#57, #116 (a)).
const (
	ReadLimit   = 1 << 20 // kept per stream (#134 (a))
	StdoutCap   = 65536
	StderrCap   = 16384
	GrowthLimit = 4 << 20 // #134 (f)
	MaxPatterns = 50
	Marker      = "[REDACTED]"
)

var (
	marker      = []byte(Marker)
	replacement = []byte("�")
)

// Stream selects the cap and the truncated rule.
type Stream int

const (
	Stdout Stream = iota
	Stderr
)

// Captured is one stream as read from a plugin.
type Captured struct {
	Data     []byte // at most ReadLimit bytes
	Overflow bool   // more than ReadLimit bytes were produced
}

// Apply returns the text that may leave the runner and, for Stdout, whether
// it was truncated. The text is valid UTF-8 and never longer than the
// stream's cap in bytes. Stderr is never reported truncated (#113).
func (s *Set) Apply(c Captured, st Stream) (string, bool) {
	data, overflow := c.Data, c.Overflow
	if len(data) > ReadLimit {
		data, overflow = data[:ReadLimit], true
	}
	// Each run of invalid bytes becomes one U+FFFD before matching, so the
	// text matched is the text sent; U+0000 is kept (#121, #134 (c)).
	b := bytes.ToValidUTF8(data, replacement)
	for _, re := range s.res {
		var over bool
		if b, over = replace(re, b); over {
			// Fail closed: cutting the intermediate text could split a
			// secret a later pattern would have matched.
			return Marker, st == Stdout
		}
	}
	b = cutOff(b)
	limit := StderrCap
	if st == Stdout {
		limit = StdoutCap
	}
	cut := false
	if len(b) > limit {
		n := limit
		for n > 0 && !utf8.RuneStart(b[n]) {
			n--
		}
		b, cut = b[:n], true
	}
	return string(b), st == Stdout && (overflow || cut)
}

// replace returns src with every whole match of re replaced by the literal
// Marker (no capture-group expansion), and whether the result would exceed
// GrowthLimit. Once it would, the remaining matches are replaced by nothing,
// so the buffer stays within len(src) + GrowthLimit, and the caller discards
// it.
func replace(re *regexp.Regexp, src []byte) ([]byte, bool) {
	size := len(src)
	over := size > GrowthLimit
	out := re.ReplaceAllFunc(src, func(m []byte) []byte {
		if over {
			return nil
		}
		if size += len(marker) - len(m); size > GrowthLimit {
			over = true
			return nil
		}
		return marker
	})
	return out, over
}
