// TP-M10-03 (tester-m10): redaction, REQ-242, REQ-243, REQ-244; #133, #134.
// The five default patterns are read from TS §8.6 at test time (never copied
// by hand). Expected outputs come from the spec and the approved answers, not
// from the implementation. Pure Go: runs on Windows and Linux.
package redact_test

import (
	"bytes"
	"encoding/json"
	"encoding/xml"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
	"time"
	"unicode/utf8"

	"bitscan.local/agent/internal/redact"
)

const (
	repoRoot = "../../.."
	t43      = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdE"
	canary   = "M10CANARY"
)

// specPatterns returns the ```text block after "**Default redaction
// patterns**" in TS §8.6, one pattern per line (CHK-M10-H04).
func specPatterns(t testing.TB) []string {
	t.Helper()
	raw, err := fs.ReadFile(os.DirFS(filepath.Join(repoRoot, "docs", "spec")), "Technical_Specification.md")
	if err != nil {
		t.Fatalf("read TS: %v", err)
	}
	text := strings.ReplaceAll(string(raw), "\r\n", "\n")
	i := strings.Index(text, "**Default redaction patterns**")
	if i < 0 {
		t.Fatal("TS: heading not found")
	}
	rest := text[i:]
	j := strings.Index(rest, "```text\n")
	if j < 0 {
		t.Fatal("TS: text fence not found")
	}
	block := rest[j+len("```text\n"):]
	k := strings.Index(block, "\n```")
	if k < 0 {
		t.Fatal("TS: fence end not found")
	}
	lines := strings.Split(block[:k], "\n")
	if len(lines) != 5 {
		t.Fatalf("TS: %d default patterns, want 5", len(lines))
	}
	return lines
}

func defaults(t testing.TB) *redact.Set {
	t.Helper()
	s, err := redact.Compile(specPatterns(t))
	if err != nil {
		t.Fatalf("defaults refused: %v", err)
	}
	return s
}

func mustCompile(t testing.TB, p ...string) *redact.Set {
	t.Helper()
	if p == nil {
		p = []string{}
	}
	s, err := redact.Compile(p)
	if err != nil {
		t.Fatalf("Compile(%q): %v", p, err)
	}
	return s
}

func out(s *redact.Set, in string) string {
	o, _ := s.Apply(redact.Captured{Data: []byte(in)}, redact.Stdout)
	return o
}

// CHK-M10-011
func TestConstants(t *testing.T) {
	if redact.ReadLimit != 1048576 || redact.StdoutCap != 65536 || redact.StderrCap != 16384 ||
		redact.GrowthLimit != 4194304 || redact.MaxPatterns != 50 || redact.Marker != "[REDACTED]" {
		t.Fatalf("constants %d %d %d %d %d %q", redact.ReadLimit, redact.StdoutCap, redact.StderrCap,
			redact.GrowthLimit, redact.MaxPatterns, redact.Marker)
	}
}

// CHK-M10-012: REQ-244 (1) refusals; the error names the index, never the
// pattern.
func TestCompileRefusals(t *testing.T) {
	fifty1 := make([]string, 51)
	for i := range fifty1 {
		fifty1[i] = "a"
	}
	if _, err := redact.Compile(fifty1); !errors.Is(err, redact.ErrTooMany) {
		t.Errorf("51 patterns: %v", err)
	}
	bad := []string{"(", "a{1001}", `\C`, "x*", "(?:)", "a?", `\b`, "^", "$", `\B`, `\z`, `\A`,
		"(a|)", "a{0,3}", "(a*)+", "(?i)", "", "(?m)^$", "[a-z]*", "()", "(?:a?b?)", "|a", "a|(?:)", `\b\B`}
	for _, p := range bad {
		for _, pos := range []int{0, 3} {
			list := []string{"ok1", "ok2", "ok3"}
			list = append(list[:pos], append([]string{p}, list[pos:]...)...)
			s, err := redact.Compile(list)
			if err == nil || s != nil {
				t.Errorf("%q at %d accepted", p, pos)
				continue
			}
			var pe *redact.PatternError
			if !errors.As(err, &pe) || pe.Index != pos {
				t.Errorf("%q at %d: err %v (want PatternError index %d)", p, pos, err, pos)
			}
		}
	}
	for _, p := range []string{"x*", "(?:)", "a?", `\b`, "^"} {
		_, err := redact.Compile([]string{p})
		if !errors.Is(err, redact.ErrEmptyMatch) {
			t.Errorf("%q: %v, want ErrEmptyMatch", p, err)
		}
	}
	// The error text holds no pattern text.
	for _, p := range []string{canary + "(", "(?:" + canary + ")*", canary + "{1001}", "(?i)" + canary + "?|"} {
		_, err := redact.Compile([]string{p})
		if err == nil {
			t.Fatalf("%q accepted", p)
		}
		if strings.Contains(err.Error(), canary) {
			t.Errorf("error text quotes the pattern: %q", err.Error())
		}
	}
}

// CHK-M10-013: REQ-244 (2) accepted lists.
func TestCompileAccepts(t *testing.T) {
	fifty := make([]string, 50)
	for i := range fifty {
		fifty[i] = "x" + strings.Repeat("y", i)
	}
	lists := [][]string{
		fifty, specPatterns(t), {}, nil,
		{"a+", "[a-z]", ".", "(?s).", "ab|c", `\d+`, "a(b*)", "a{1,3}", `\bx`, `x\b`, "(?i)abc", "^a", "a$", `\Aa`},
	}
	for i, l := range lists {
		if s, err := redact.Compile(l); err != nil || s == nil {
			t.Errorf("list %d refused: %v", i, err)
		}
	}
}

// fixture: input → exact output with the five TS defaults (stdout).
type fixture struct{ name, in, want string }

// CHK-M10-014: REQ-243 (1) fixtures.
func TestDefaultFixtures(t *testing.T) {
	s := defaults(t)
	fixtures := []fixture{
		{"shadow line", "root:$6$Zm9vYmFy$hashhashhash/./Ab:19000:0:99999:7:::", "root:[REDACTED]:19000:0:99999:7:::"},
		{"shadow yescrypt", "alice:$y$j9T$F5Jx5fExrKuPp53xLKQ..1$X3DX6M94c7o.9agCG9G317fhZg9SqC.5i5rd.RhAtQ7:19500:0:99999:7:::",
			"alice:[REDACTED]:19500:0:99999:7:::"},
		{"full PEM key", "before\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA7\nabc+/=\n-----END RSA PRIVATE KEY-----\nafter",
			"before\n[REDACTED]\nafter"},
		{"cut-off PEM key", "before\n-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg", "before\n[REDACTED]"},
		{"full OpenSSH key", "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----", "[REDACTED]"},
		{"key=value", "password=hunter2", "[REDACTED]"},
		{"key: value", "api_key: abc", "[REDACTED]"},
		{"key = value mid-line", "DB_PASSWORD = s3cr3t # comment", "DB_[REDACTED] # comment"},
		{"token: list", "token:abc,def ghi", "[REDACTED] ghi"},
		{"bsa token", "bsa_" + t43, "[REDACTED]"},
		{"bsu bearer", "Authorization: Bearer bsu_" + t43, "Authorization: Bearer [REDACTED]"},
		{"bse in token= (patterns in order)", "enroll.token=bse_" + t43, "enroll.[REDACTED]"},
		{"bsk token", "key bsk_" + t43, "key [REDACTED]"},
		{"AKIA", "aws_access_key_id = AKIAIOSFODNN7EXAMPLE", "aws_access_key_id = [REDACTED]"},
		{"ASIA", "ASIAY34FZKBOKMUTVV7A", "[REDACTED]"},
		{"unchanged install ok installed", "install ok installed", "install ok installed"},
		{"unchanged PasswordAuthentication", "PasswordAuthentication no", "PasswordAuthentication no"},
		{"unchanged passwd files", "passwd: files", "passwd: files"},
		{"unchanged locked shadow", "root:!:19000:0:99999:7:::", "root:!:19000:0:99999:7:::"},
		{"unchanged sshd -T line", "permitrootlogin no\nmaxauthtries 4", "permitrootlogin no\nmaxauthtries 4"},
	}
	for _, f := range fixtures {
		t.Run(f.name, func(t *testing.T) {
			got, trunc := s.Apply(redact.Captured{Data: []byte(f.in)}, redact.Stdout)
			if got != f.want || trunc {
				t.Fatalf("got %q (truncated %v), want %q", got, trunc, f.want)
			}
		})
	}
}

// CHK-M10-014 (samples): every ExpectedResult text of bits/samples, and
// representative outputs the regex ones accept, are unchanged.
func TestSampleOutputsUnchanged(t *testing.T) {
	s := defaults(t)
	files, err := filepath.Glob(filepath.Join(repoRoot, "bits", "samples", "*.bit"))
	if err != nil || len(files) < 2 {
		t.Fatalf("samples: %v %v", files, err)
	}
	type plugin struct {
		Expected string `xml:"ExpectedResult"`
	}
	type policy struct {
		Plugins []plugin `xml:"PluginsGroups>Plugin"`
	}
	n := 0
	for _, f := range files {
		raw, err := fs.ReadFile(os.DirFS(filepath.Dir(f)), filepath.Base(f))
		if err != nil {
			t.Fatal(err)
		}
		var p policy
		if err := xml.Unmarshal(raw, &p); err != nil {
			t.Fatalf("%s: %v", f, err)
		}
		for _, pl := range p.Plugins {
			n++
			if got := out(s, pl.Expected); got != pl.Expected {
				t.Errorf("%s: %q became %q", filepath.Base(f), pl.Expected, got)
			}
		}
	}
	if n < 30 {
		t.Fatalf("only %d sample plugins", n)
	}
	for _, o := range []string{"absent", "loaded=no install=yes blacklist=yes", "no", "not-installed", "0640 root root",
		"0600 root root", "ipv4=0 ipv6=0", "ipv4=0 ipv6=absent", "enabled active", "rw,nosuid,nodev,noexec,relatime",
		"3", "root", "", "PASS_MAX_DAYS 365"} {
		if got := out(s, o); got != o {
			t.Errorf("%q became %q", o, got)
		}
	}
}

// corpus is the REQ-243 (3) shared fixture.
type corpus struct {
	Cases []struct {
		Name    string     `json:"name"`
		Input   string     `json:"input"`
		Matches [][]string `json:"matches"`
	} `json:"cases"`
}

func loadCorpus(t *testing.T) corpus {
	t.Helper()
	dir := filepath.Join(repoRoot, "manager", "tests", "contract", "fixtures", "redaction")
	raw, err := fs.ReadFile(os.DirFS(dir), "corpus.json")
	if err != nil {
		t.Fatal(err)
	}
	var c corpus
	if err := json.Unmarshal(raw, &c); err != nil {
		t.Fatal(err)
	}
	if len(c.Cases) < 40 {
		t.Fatalf("%d corpus cases", len(c.Cases))
	}
	return c
}

// spans derives the expected byte spans by sequential search.
func spans(t *testing.T, input string, texts []string) [][2]int {
	t.Helper()
	var outS [][2]int
	pos := 0
	for _, m := range texts {
		i := strings.Index(input[pos:], m)
		if i < 0 {
			t.Fatalf("expected match %q not in input after %d", m, pos)
		}
		outS = append(outS, [2]int{pos + i, pos + i + len(m)})
		pos += i + len(m)
	}
	return outS
}

// CHK-M10-015 (Go half) and CHK-M10-016 (Go half): the TS list has five
// entries that compile in Go, and each finds exactly the corpus matches.
func TestCorpusGoRegexp(t *testing.T) {
	pats := specPatterns(t)
	res := make([]*regexp.Regexp, len(pats))
	for i, p := range pats {
		res[i] = regexp.MustCompile(p)
	}
	for _, c := range loadCorpus(t).Cases {
		if len(c.Matches) != 5 {
			t.Fatalf("%s: %d match lists", c.Name, len(c.Matches))
		}
		for pi, re := range res {
			want := spans(t, c.Input, c.Matches[pi])
			var got [][2]int
			for _, loc := range re.FindAllStringIndex(c.Input, -1) {
				got = append(got, [2]int{loc[0], loc[1]})
			}
			if len(got) != len(want) {
				t.Errorf("%s pattern %d: got %v want %v", c.Name, pi+1, got, want)
				continue
			}
			for k := range got {
				if got[k] != want[k] {
					t.Errorf("%s pattern %d: got %v want %v", c.Name, pi+1, got, want)
					break
				}
			}
		}
	}
}

// CHK-M10-017: REQ-242 (5) literal replacement, list order.
func TestLiteralAndOrder(t *testing.T) {
	if got := out(mustCompile(t, "(a)(b)"), "ab"); got != "[REDACTED]" {
		t.Errorf("(a)(b): %q", got)
	}
	if got := out(mustCompile(t, "a"), "a$1${1}"); got != "[REDACTED]$1${1}" {
		t.Errorf("a on a$1: %q", got)
	}
	if got := out(mustCompile(t, "(?P<x>a)b"), "ab ab"); got != "[REDACTED] [REDACTED]" {
		t.Errorf("named group: %q", got)
	}
	// Order: the second pattern sees the first one's output.
	if got := out(mustCompile(t, "secret", `\[REDACTED\]`), "secret"); got != "[REDACTED]" {
		t.Errorf("order 1: %q", got)
	}
	if got := out(mustCompile(t, "DACT", "secret"), "secret"); got != "[REDACTED]" {
		t.Errorf("order 2 (DACT before): %q", got)
	}
	if got := out(mustCompile(t, "secret", "DACT"), "secret"); got != "[RE[REDACTED]ED]" {
		t.Errorf("order 3 (DACT after): %q", got)
	}
}

// CHK-M10-018: the #133 cut-off rule with an empty list.
func TestCutOffRule(t *testing.T) {
	s := mustCompile(t)
	cases := []fixture{
		{"rsa", "x\n-----BEGIN RSA PRIVATE KEY-----\nMIIE", "x\n[REDACTED]"},
		{"openssh", "-----BEGIN OPENSSH PRIVATE KEY-----\nb3Bl", "[REDACTED]"},
		{"ec", "a -----BEGIN EC PRIVATE KEY-----", "a [REDACTED]"},
		{"encrypted", "-----BEGIN ENCRYPTED PRIVATE KEY-----\nzz", "[REDACTED]"},
		{"bare", "-----BEGIN PRIVATE KEY-----\nMII\nmore\nlines", "[REDACTED]"},
		{"complete block unchanged", "-----BEGIN PRIVATE KEY-----\nA\n-----END PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----\nA\n-----END PRIVATE KEY-----"},
		{"complete then cut", "-----BEGIN PRIVATE KEY-----\nA\n-----END PRIVATE KEY-----\nmid\n-----BEGIN RSA PRIVATE KEY-----\nB",
			"-----BEGIN PRIVATE KEY-----\nA\n-----END PRIVATE KEY-----\nmid\n[REDACTED]"},
		{"public key", "-----BEGIN PUBLIC KEY-----\nabc", "-----BEGIN PUBLIC KEY-----\nabc"},
		{"certificate", "-----BEGIN CERTIFICATE-----\nabc", "-----BEGIN CERTIFICATE-----\nabc"},
		{"lowercase not a marker", "-----begin private key-----\nabc", "-----begin private key-----\nabc"},
		{"A, B, END B: A has an END after it", "-----BEGIN PRIVATE KEY-----\nA\n-----BEGIN PRIVATE KEY-----\nB\n-----END PRIVATE KEY-----",
			"-----BEGIN PRIVATE KEY-----\nA\n-----BEGIN PRIVATE KEY-----\nB\n-----END PRIVATE KEY-----"},
		{"END glued to BEGIN (impl note)", "-----END RSA PRIVATE KEY-----BEGIN RSA PRIVATE KEY-----\nsecret", "-----END RSA PRIVATE KEY[REDACTED]"},
		{"two cut blocks", "-----BEGIN PRIVATE KEY-----\nA\n-----BEGIN PRIVATE KEY-----\nB", "[REDACTED]"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := out(s, c.in); got != c.want {
				t.Fatalf("got %q want %q", got, c.want)
			}
		})
	}
	// The rule applies with a non-empty list that lacks pattern 2.
	p := specPatterns(t)
	noP2 := mustCompile(t, p[0], p[2], p[3], p[4])
	if got := out(noP2, "k\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3Bl"); got != "k\n[REDACTED]" {
		t.Errorf("without pattern 2: %q", got)
	}
}

// CHK-M10-019: REQ-242 (2) a key whose END is beyond the read limit.
func TestKeyCutByReadLimit(t *testing.T) {
	body := strings.Repeat("QUJDREVGR0hJSktMTU5PUA==\n", 10)
	key := "-----BEGIN RSA PRIVATE KEY-----\n" + body
	prefix := strings.Repeat("x", redact.ReadLimit-100)
	full := prefix + key + "\n-----END RSA PRIVATE KEY-----\n"
	data := []byte(full)[:redact.ReadLimit]
	p := specPatterns(t)
	for name, s := range map[string]*redact.Set{
		"defaults":     defaults(t),
		"no pattern 2": mustCompile(t, p[0], p[2], p[3], p[4]),
		"empty list":   mustCompile(t),
	} {
		got, trunc := s.Apply(redact.Captured{Data: data, Overflow: true}, redact.Stdout)
		if strings.Contains(got, "QUJD") || strings.Contains(got, "BEGIN") || !trunc || len(got) > redact.StdoutCap {
			t.Errorf("%s: key body or marker left, truncated %v, len %d", name, trunc, len(got))
		}
		// The whole kept window is filler (the key started after 65,536).
		if strings.Trim(got, "x") != "" {
			t.Errorf("%s: unexpected text %q", name, strings.Trim(got, "x"))
		}
	}
	// The same with the BEGIN inside the stdout window.
	short := "head\n" + key
	got, _ := mustCompile(t).Apply(redact.Captured{Data: []byte(short)}, redact.Stdout)
	if got != "head\n[REDACTED]" {
		t.Errorf("short cut key: %q", got)
	}
}

// CHK-M10-020: REQ-242 (1), CHK-M10-344: a secret at or across the 64 KiB cut.
func TestSecretAtTheCap(t *testing.T) {
	s := defaults(t)
	tok := "bsa_" + t43
	for _, at := range []int{65530, 65520, 65536 - len(tok), 65535, 65536} {
		// The filler is not a word character, so the token keeps its \b.
		in := strings.Repeat(".", at) + tok + "\n" + strings.Repeat("y", 200000)
		got, trunc := s.Apply(redact.Captured{Data: []byte(in)}, redact.Stdout)
		if len(got) > redact.StdoutCap || !trunc {
			t.Fatalf("at %d: len %d truncated %v", at, len(got), trunc)
		}
		tail := got[at:]
		for n := 2; n <= len(tok); n++ {
			if strings.Contains(got, tok[:n]) {
				t.Fatalf("at %d: prefix %q of the token returned (tail %q)", at, tok[:n], tail[:min(len(tail), 20)])
			}
		}
		if at+len(redact.Marker) <= redact.StdoutCap && !strings.Contains(got, redact.Marker) {
			t.Fatalf("at %d: no marker", at)
		}
	}
	// A secret straddling the stderr cap.
	in := strings.Repeat("x", 16380) + "password=" + strings.Repeat("Z", 30)
	got, trunc := s.Apply(redact.Captured{Data: []byte(in)}, redact.Stderr)
	if strings.Contains(got, "pass") || strings.Contains(got, "ZZ") || trunc || len(got) > redact.StderrCap {
		t.Fatalf("stderr straddle: tail %q trunc %v", got[16370:], trunc)
	}
}

// CHK-M10-021: REQ-242 (3) caps on rune boundaries.
func TestCapsAndRuneBoundaries(t *testing.T) {
	s := mustCompile(t)
	type tc struct {
		name    string
		in      string
		st      redact.Stream
		wantLen int
		trunc   bool
	}
	cases := []tc{
		{"65536 ascii", strings.Repeat("a", 65536), redact.Stdout, 65536, false},
		{"65537 ascii", strings.Repeat("a", 65537), redact.Stdout, 65536, true},
		{"32769 e-acute", strings.Repeat("é", 32769), redact.Stdout, 65536, true},
		{"21846 euro", strings.Repeat("€", 21846), redact.Stdout, 65535, true},
		{"16385 emoji", strings.Repeat("😀", 16385), redact.Stdout, 65536, true},
		{"a + 16384 emoji", "a" + strings.Repeat("😀", 16384), redact.Stdout, 65533, true},
		{"stderr 16384", strings.Repeat("e", 16384), redact.Stderr, 16384, false},
		{"stderr 16385", strings.Repeat("e", 16385), redact.Stderr, 16384, false},
		{"stderr 8193 e-acute", strings.Repeat("é", 8193), redact.Stderr, 16384, false},
		{"stderr a + 8192 e-acute", "a" + strings.Repeat("é", 8192), redact.Stderr, 16383, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, trunc := s.Apply(redact.Captured{Data: []byte(c.in)}, c.st)
			if len(got) != c.wantLen || trunc != c.trunc || !utf8.ValidString(got) || !strings.HasPrefix(c.in, got) {
				t.Fatalf("len %d (want %d) truncated %v (want %v) valid %v prefix %v",
					len(got), c.wantLen, trunc, c.trunc, utf8.ValidString(got), strings.HasPrefix(c.in, got))
			}
		})
	}
}

// CHK-M10-022: REQ-242 (4) invalid UTF-8 becomes U+FFFD before matching.
func TestInvalidUTF8(t *testing.T) {
	s := defaults(t)
	empty := mustCompile(t)
	if got := out(empty, "a\xff\xfe\xfdb"); got != "a�b" {
		t.Errorf("run of three: %q", got)
	}
	if got := out(empty, "a\xffb\xfec"); got != "a�b�c" {
		t.Errorf("two runs: %q", got)
	}
	if got := out(empty, "a\x00b"); got != "a\x00b" {
		t.Errorf("NUL: %q", got)
	}
	if got := out(empty, "\xe2\x82"); got != "�" {
		t.Errorf("cut rune: %q", got)
	}
	if got := out(s, "password=\xffabc tail"); got != "[REDACTED] tail" {
		t.Errorf("password with invalid byte: %q", got)
	}
	if got := out(mustCompile(t, "�"), "x\xffy"); got != "x[REDACTED]y" {
		t.Errorf("the replacement is what patterns see: %q", got)
	}
	in := strings.Repeat("a", 65535) + "\xff"
	got, trunc := empty.Apply(redact.Captured{Data: []byte(in)}, redact.Stdout)
	if len(got) != 65535 || !trunc {
		t.Errorf("FFFD past the cap: len %d trunc %v", len(got), trunc)
	}
	for _, in := range []string{strings.Repeat("\xff", 70000), strings.Repeat("a\xc3", 40000), strings.Repeat("\x01", 70000)} {
		for _, st := range []redact.Stream{redact.Stdout, redact.Stderr} {
			got, _ := s.Apply(redact.Captured{Data: []byte(in)}, st)
			capN := redact.StdoutCap
			if st == redact.Stderr {
				capN = redact.StderrCap
			}
			b, err := json.Marshal(got)
			if err != nil {
				t.Fatal(err)
			}
			var back string
			if err := json.Unmarshal(b, &back); err != nil || back != got || len(back) > capN || !utf8.ValidString(got) {
				t.Errorf("json round trip: len %d cap %d same %v", len(back), capN, back == got)
			}
		}
	}
}

// CHK-M10-023: REQ-242 (6) overflow sets truncated for stdout only.
func TestOverflowTruncated(t *testing.T) {
	big := bytes.Repeat([]byte("a"), redact.ReadLimit)
	got, trunc := mustCompile(t, "a+").Apply(redact.Captured{Data: big, Overflow: true}, redact.Stdout)
	if got != "[REDACTED]" || !trunc {
		t.Errorf("1 MiB + 1 shrunk: %q %v", got, trunc)
	}
	if got, trunc := mustCompile(t).Apply(redact.Captured{Data: []byte("short"), Overflow: true}, redact.Stdout); got != "short" || !trunc {
		t.Errorf("short overflow: %q %v", got, trunc)
	}
	if _, trunc := mustCompile(t).Apply(redact.Captured{Data: []byte("short"), Overflow: true}, redact.Stderr); trunc {
		t.Error("stderr overflow reported truncated")
	}
	if _, trunc := mustCompile(t).Apply(redact.Captured{Data: []byte("short")}, redact.Stdout); trunc {
		t.Error("no overflow, no cut: truncated")
	}
}

// CHK-M10-024: REQ-242 (7) growth guard, its boundary and memory.
func TestGrowthGuard(t *testing.T) {
	letters := bytes.Repeat([]byte("aB"), redact.ReadLimit/2)
	s := mustCompile(t, "[a-z]", "[A-Z]")
	if got, trunc := s.Apply(redact.Captured{Data: letters}, redact.Stdout); got != "[REDACTED]" || !trunc {
		t.Errorf("stdout guard: %q %v", got[:min(len(got), 40)], trunc)
	}
	if got, trunc := s.Apply(redact.Captured{Data: letters}, redact.Stderr); got != "[REDACTED]" || trunc {
		t.Errorf("stderr guard: %q %v", got[:min(len(got), 40)], trunc)
	}
	one := mustCompile(t, "a")
	at := strings.Repeat("a", 419430) // ×10 = 4,194,300
	if got, trunc := one.Apply(redact.Captured{Data: []byte(at + "zzzz")}, redact.Stdout); got == "[REDACTED]" || len(got) != 65536 || !trunc {
		t.Errorf("exactly 4 MiB: guard tripped or wrong cut (len %d)", len(got))
	}
	if got, _ := one.Apply(redact.Captured{Data: []byte(at + "zzzzz")}, redact.Stdout); got != "[REDACTED]" {
		t.Errorf("4 MiB + 1: guard not tripped (len %d)", len(got))
	}
	// Memory bound (#134 (f), MemoryMax=256M): the peak heap while one
	// guarded Apply runs, sampled every millisecond. Total allocation is
	// recorded only (under -race, sync.Pool is disabled, so regexp machines
	// are reallocated per match: churn, not live memory).
	var m0, m1 runtime.MemStats
	runtime.GC()
	runtime.ReadMemStats(&m0)
	stop := make(chan struct{})
	peak := make(chan uint64)
	go func() {
		var mx uint64
		var ms runtime.MemStats
		for {
			runtime.ReadMemStats(&ms)
			mx = max(mx, ms.HeapAlloc)
			select {
			case <-stop:
				peak <- mx
				return
			case <-time.After(time.Millisecond):
			}
		}
	}()
	_, _ = s.Apply(redact.Captured{Data: letters}, redact.Stdout)
	close(stop)
	top := <-peak
	runtime.ReadMemStats(&m1)
	t.Logf("RECORDED: guarded Apply over 1 MiB: peak heap %d bytes above a %d-byte baseline; %d bytes allocated in total",
		top-min(top, m0.HeapAlloc), m0.HeapAlloc, m1.TotalAlloc-m0.TotalAlloc)
	if top > m0.HeapAlloc+64<<20 {
		t.Errorf("peak heap %d bytes above the baseline (> 64 MiB)", top-m0.HeapAlloc)
	}
}

// Apply on input longer than ReadLimit (a caller bug) still caps and flags.
func TestDataOverReadLimit(t *testing.T) {
	got, trunc := mustCompile(t).Apply(redact.Captured{Data: bytes.Repeat([]byte("q"), redact.ReadLimit+10)}, redact.Stdout)
	if len(got) != 65536 || !trunc {
		t.Fatalf("len %d trunc %v", len(got), trunc)
	}
}

// Purity (CHK-M10-010 analogue for redact): only the standard library, no
// logging, no OS access.
func TestRedactImports(t *testing.T) {
	ents, err := os.ReadDir(".")
	if err != nil {
		t.Fatal(err)
	}
	allowed := map[string]bool{"bytes": true, "errors": true, "fmt": true, "regexp": true, "regexp/syntax": true,
		"unicode/utf8": true, "strings": true, "strconv": true, "unicode": true}
	re := regexp.MustCompile(`(?m)^\s*(?:import\s+)?"([^"]+)"`)
	for _, e := range ents {
		n := e.Name()
		if !strings.HasSuffix(n, ".go") || strings.HasSuffix(n, "_test.go") {
			continue
		}
		if strings.Contains(n, "_linux") || strings.Contains(n, "_windows") {
			t.Errorf("platform file %s", n)
		}
		src, err := fs.ReadFile(os.DirFS("."), n)
		if err != nil {
			t.Fatal(err)
		}
		head := string(src)
		if i := strings.Index(head, "\nfunc "); i > 0 {
			head = head[:i]
		}
		for _, m := range re.FindAllStringSubmatch(head, -1) {
			if !allowed[m[1]] {
				t.Errorf("%s imports %s", n, m[1])
			}
		}
	}
}
