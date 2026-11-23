package redact

import (
	"bytes"
	"unicode/utf8"
)

// ApplyFile redacts one whole ClusterMAX file (TS §3.8): invalid UTF-8
// replaced, the job's patterns applied in list order, the cut-off
// private-key rule, then a cut at a UTF-8 boundary to limit bytes. It
// reports whether the file was cut. When the markers would grow the file by
// more than GrowthLimit, the whole file becomes one Marker (fail closed).
func (s *Set) ApplyFile(data []byte, limit int) ([]byte, bool) {
	b := bytes.ToValidUTF8(data, replacement)
	room := len(b) + GrowthLimit
	for _, re := range s.res {
		size, over := len(b), false
		b = re.ReplaceAllFunc(b, func(m []byte) []byte {
			if over {
				return nil
			}
			if size += len(marker) - len(m); size > room {
				over = true
				return nil
			}
			return marker
		})
		if over {
			return []byte(Marker), false
		}
	}
	b = cutOff(b)
	if len(b) <= limit {
		return b, false
	}
	n := limit
	for n > 0 && !utf8.RuneStart(b[n]) {
		n--
	}
	return b[:n], true
}
