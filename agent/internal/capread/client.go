package capread

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"regexp"
	"time"
)

const (
	clientTimeout = 30 * time.Second // connect to the end of the answer (#142 (f))
	maxLine       = 64               // the first answer line
	maxAnswer     = 1 << 20          // the helper never sends more stdout
)

// wordRe bounds a helper's error word before it is printed (TS §3.7 L484).
var wordRe = regexp.MustCompile(`^[a-z0-9_ ]{1,40}$`)

// Client is `bitscan-capread <name>` as a plugin calls it (REQ-253). It
// sends only the name to the helper at socket, writes the helper's output to
// stdout and returns 0. On an error answer, a missing or refused socket (the
// helper is not enabled) or 30 s without an answer it writes one line to
// stderr and returns 1. Any other argument list returns 2 and connects
// nowhere. A partial answer is never printed.
func Client(args []string, socket string, stdout, stderr io.Writer) int {
	if len(args) != 1 || !Known(args[0]) {
		_, _ = fmt.Fprintln(stderr, "bitscan-capread: usage: bitscan-capread nft_ruleset|audit_rules")
		return 2
	}
	fail := func(word string) int {
		_, _ = fmt.Fprintln(stderr, "bitscan-capread: "+word)
		return 1
	}
	c, err := (&net.Dialer{Timeout: clientTimeout}).Dial("unix", socket)
	if err != nil {
		return fail("not enabled")
	}
	defer func() { _ = c.Close() }()
	_ = c.SetDeadline(time.Now().Add(clientTimeout))
	lost := func(err error) int {
		if errors.Is(err, os.ErrDeadlineExceeded) {
			return fail("timeout")
		}
		return fail("no answer")
	}
	if _, err := io.WriteString(c, args[0]+"\n"); err != nil {
		return lost(err)
	}
	br := bufio.NewReaderSize(c, maxLine)
	line, err := br.ReadSlice('\n')
	switch {
	case errors.Is(err, bufio.ErrBufferFull):
		return fail("bad answer")
	case err != nil:
		return lost(err)
	}
	line = bytes.TrimSuffix(line, []byte("\n"))
	if word, ok := bytes.CutPrefix(line, []byte("error ")); ok {
		if !wordRe.Match(word) {
			return fail("bad answer")
		}
		return fail(string(word))
	}
	if string(line) != "ok" {
		return fail("bad answer")
	}
	out, err := io.ReadAll(io.LimitReader(br, maxAnswer+1))
	switch {
	case err != nil:
		return lost(err)
	case len(out) > maxAnswer:
		return fail("too_large")
	}
	if _, err := stdout.Write(out); err != nil {
		return 1
	}
	return 0
}
