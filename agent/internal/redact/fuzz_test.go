// TP-M10-03 fuzz and property rows (tester-m10): REQ-242 (8), CHK-M10-080,
// -081, -083. Secrets with random bodies are inserted into random text, across
// the 16,384, 65,536 and 1,048,576 boundaries. With the five TS defaults no
// secret's random body may appear in the output, and the output never exceeds
// its cap and is always valid UTF-8.
package redact_test

import (
	"regexp"
	"strings"
	"testing"
	"unicode/utf8"

	"bitscan.local/agent/internal/redact"
)

const (
	b64   = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
	b64u  = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
	upnum = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	salt  = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789./"
)

func randFrom(r *prng, alphabet string, n int) string {
	b := make([]byte, n)
	for i := range b {
		b[i] = alphabet[r.IntN(len(alphabet))]
	}
	return string(b)
}

// secret returns a secret text and its random body (the part that must never
// leave). Each secret is preceded by a separator so its pattern can anchor.
func secret(r *prng) (text, body string) {
	switch r.IntN(6) {
	case 0: // crypt hash in a shadow line
		body = randFrom(r, salt, 16) + "$" + randFrom(r, salt, 40)
		id := []string{"1", "2b", "5", "6", "y", "gy", "sha1", "md5"}[r.IntN(8)]
		return "\nuser:$" + id + "$" + body + ":19000:0:99999:7:::\n", body
	case 1: // a Bitscan token
		body = randFrom(r, b64u, 20+r.IntN(40))
		return " bs" + string("aeku"[r.IntN(4)]) + "_" + body + " ", body
	case 2: // AWS key id
		body = randFrom(r, upnum, 16)
		return " " + []string{"AKIA", "ASIA"}[r.IntN(2)] + body + " ", body
	case 3: // PEM block, complete or cut off at the end of the buffer
		body = randFrom(r, b64, 48+r.IntN(200))
		kind := []string{"RSA ", "EC ", "OPENSSH ", "ENCRYPTED ", ""}[r.IntN(5)]
		end := ""
		if r.IntN(2) == 0 {
			end = "\n-----END " + kind + "PRIVATE KEY-----"
		}
		return "\n-----BEGIN " + kind + "PRIVATE KEY-----\n" + body + end + "\n", body
	case 4: // key=value or key: value
		body = randFrom(r, b64u, 12+r.IntN(30))
		key := []string{"password", "Secret", "API_KEY", "api-key", "TOKEN", "apikey"}[r.IntN(6)]
		sep := []string{"=", ": ", " = ", ":\t"}[r.IntN(4)]
		return "\n" + key + sep + body + "\n", body
	default: // crypt hash after a space
		body = randFrom(r, salt, 30)
		return " $6$" + body + " ", body
	}
}

// filler is text that holds no secret and no word character next to a
// secret's start (the separators above handle the anchors).
func filler(r *prng, n int) string {
	const alpha = "abcdefghij klmnop\nqrstuvwxyz 0123456789.,;-()é€"
	// A random 4 KiB chunk (with an invalid byte now and then), repeated:
	// cheap for 1 MiB fills, still varied per case.
	var sb strings.Builder
	for sb.Len() < 4096 {
		sb.WriteByte(alpha[r.IntN(len(alpha))])
		if r.IntN(500) == 0 {
			sb.WriteString("\xff")
		}
	}
	chunk := sb.String()
	out := strings.Repeat(chunk, n/len(chunk)+1)
	return out[:n]
}

func checkOne(t *testing.T, s *redact.Set, data []byte, overflow bool, bodies []string) {
	t.Helper()
	for _, st := range []redact.Stream{redact.Stdout, redact.Stderr} {
		got, trunc := s.Apply(redact.Captured{Data: data, Overflow: overflow}, st)
		capN := redact.StdoutCap
		if st == redact.Stderr {
			capN = redact.StderrCap
			if trunc {
				t.Fatal("stderr truncated")
			}
		}
		if len(got) > capN || !utf8.ValidString(got) {
			t.Fatalf("stream %d: len %d valid %v", st, len(got), utf8.ValidString(got))
		}
		for _, b := range bodies {
			// The 8-byte window of a random body is long enough that filler
			// never forms it by chance.
			for i := 0; i+8 <= len(b); i++ {
				if strings.Contains(got, b[i:i+8]) {
					t.Fatalf("stream %d: secret body %q leaked (window %q)", st, b, b[i:i+8])
				}
			}
		}
	}
}

// CHK-M10-083: deterministic property run, every secret type straddling every
// boundary.
func TestPropertySecretsNeverLeak(t *testing.T) {
	s := defaults(t)
	r := newPRNG(20261030)
	n := 0
	for _, boundary := range []int{redact.StderrCap, redact.StdoutCap, redact.ReadLimit} {
		rounds := 120
		if boundary == redact.ReadLimit {
			rounds = 24 // each case redacts 1 MiB twice; keeps -race runs short
		}
		for range rounds {
			text, body := secret(r)
			// Place the secret so it starts up to 60 bytes before the boundary.
			startAt := boundary - r.IntN(60) - 1
			if startAt < 0 {
				startAt = 0
			}
			data := filler(r, startAt) + text + filler(r, 300)
			overflow := false
			if len(data) > redact.ReadLimit {
				data, overflow = data[:redact.ReadLimit], true
			}
			checkOne(t, s, []byte(data), overflow, []string{body})
			n++
		}
	}
	// Many secrets at random places in a medium buffer.
	for range 300 {
		var sb strings.Builder
		var bodies []string
		for range 1 + r.IntN(12) {
			sb.WriteString(filler(r, r.IntN(9000)))
			text, body := secret(r)
			sb.WriteString(text)
			bodies = append(bodies, body)
		}
		checkOne(t, s, []byte(sb.String()), false, bodies)
		n++
	}
	t.Logf("%d property cases", n)
}

// CHK-M10-080: FuzzApply. The fuzzer drives the filler, the secret choice and
// the offset; the seed corpus runs in every normal test run.
func FuzzApply(f *testing.F) {
	f.Add([]byte("install ok installed"), uint64(1), uint32(0))
	f.Add([]byte("\xff\xfe password"), uint64(2), uint32(65530))
	f.Add([]byte(strings.Repeat("é", 40000)), uint64(3), uint32(65535))
	f.Add([]byte("-----BEGIN PRIVATE KEY-----"), uint64(4), uint32(16380))
	f.Add([]byte{}, uint64(5), uint32(1048570))
	s := defaults(f)
	f.Fuzz(func(t *testing.T, fill []byte, seed uint64, offset uint32) {
		r := newPRNG(seed)
		text, body := secret(r)
		// Use the fuzzed bytes as filler, repeated to reach the offset; strip
		// characters that could glue onto a secret's anchor (a word character
		// right before it is handled by the separators already).
		off := int(offset % (redact.ReadLimit + 1))
		var sb strings.Builder
		if len(fill) == 0 {
			fill = []byte(".")
		}
		for sb.Len() < off {
			sb.Write(fill)
		}
		pre := sb.String()
		if len(pre) > off {
			pre = pre[:off]
		}
		data := pre + text
		overflow := false
		if len(data) > redact.ReadLimit {
			data, overflow = data[:redact.ReadLimit], true
		}
		// The fuzzed filler itself could contain the body window only by a
		// ~2^-48 chance; the body is random per seed.
		checkOne(t, s, []byte(data), overflow, []string{body})
	})
}

// CHK-M10-081: FuzzCompile. No panic; an accepted pattern never matches the
// empty string anywhere in a set of probe strings.
func FuzzCompile(f *testing.F) {
	for _, p := range []string{"a", "x*", `\b`, "(?i)abc", "a|", "(a*)+b", "[^a]", `\pL`, "a{2,}", "(?s).*?x", `\Ba`} {
		f.Add(p)
	}
	probes := []string{"", "a", "\n", "ab ba", "x\x00y", "ééé", "aaaaaaaaaa", "AbC dEf", "token=1"}
	f.Fuzz(func(t *testing.T, p string) {
		s, err := redact.Compile([]string{p})
		if err != nil {
			if s != nil {
				t.Fatal("non-nil Set with an error")
			}
			return
		}
		re, cerr := compileGo(p)
		if cerr != nil {
			t.Fatalf("Compile accepted %q that Go refuses: %v", p, cerr)
		}
		for _, pr := range probes {
			for _, loc := range re.FindAllStringIndex(pr, -1) {
				if loc[0] == loc[1] {
					t.Fatalf("accepted pattern %q matches empty at %d of %q", p, loc[0], pr)
				}
			}
			got, _ := s.Apply(redact.Captured{Data: []byte(pr)}, redact.Stdout)
			if !utf8.ValidString(got) || len(got) > redact.StdoutCap {
				t.Fatalf("bad output for %q on %q", p, pr)
			}
		}
	})
}

func compileGo(p string) (*regexp.Regexp, error) { return regexp.Compile(p) }

// prng is splitmix64: deterministic test randomness without math/rand
// (the inputs only need to vary, not to be unpredictable).
type prng struct{ x uint64 }

func newPRNG(seed uint64) *prng { return &prng{x: seed} }

func (p *prng) IntN(n int) int {
	p.x += 0x9e3779b97f4a7c15
	z := p.x
	z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9
	z = (z ^ (z >> 27)) * 0x94d049bb133111eb
	z ^= z >> 31
	return int(z % uint64(n)) //nolint:gosec // n > 0 and small; the result is < n
}
