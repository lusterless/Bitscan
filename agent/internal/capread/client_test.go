// TP-M10-14 client half (tester-m10c): `bitscan-capread <name>` as a plugin
// calls it, REQ-253 (1), (2); #142 (f), (g); decisions "TASK-226 (capread
// client and main) accepted as built". A fake helper on a Unix socket in a
// temporary directory. Portable (Windows has AF_UNIX); the reset-based row is
// in client_linux_test.go. The two no-answer rows wait out the client's 30 s
// (#142 (f), a spec value) in wall time, in parallel.
package capread

import (
	"bytes"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type fakeHelper struct {
	path  string
	conns atomic.Int32
	mu    sync.Mutex
	got   [][]byte // every byte each connection sent, until it closed
}

// helper serves each connection with answer (nil: never answer) and records
// what the client sent.
func helper(t *testing.T, answer func(c net.Conn)) *fakeHelper {
	t.Helper()
	dir, err := os.MkdirTemp("", "cr") // short: Unix socket paths are limited
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	h := &fakeHelper{path: filepath.Join(dir, "c.sock")}
	l, err := net.Listen("unix", h.path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = l.Close() })
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			h.conns.Add(1)
			go func() {
				defer func() { _ = c.Close() }()
				if answer != nil {
					answer(c)
				}
				if uc, ok := c.(*net.UnixConn); ok {
					_ = uc.CloseWrite()
				}
				_ = c.SetReadDeadline(time.Now().Add(40 * time.Second))
				b, _ := io.ReadAll(c)
				h.mu.Lock()
				h.got = append(h.got, b)
				h.mu.Unlock()
			}()
		}
	}()
	return h
}

// reply answers after reading the request line, as the real helper does.
func reply(s string) func(net.Conn) {
	return func(c net.Conn) {
		_ = c.SetReadDeadline(time.Now().Add(5 * time.Second))
		var b [64]byte
		n, _ := c.Read(b[:])
		_ = n
		_, _ = io.WriteString(c, s)
	}
}

func runClient(args []string, socket string) (int, string, string) {
	var out, errb bytes.Buffer
	code := Client(args, socket, &out, &errb)
	return code, out.String(), errb.String()
}

// CHK-M10-177 (REQ-253 (2)) at package level: any other argument list exits
// 2 with the usage line and never connects; an unknown name is refused before
// any connection.
func TestClientArgsRefusedLocally(t *testing.T) {
	h := helper(t, reply("ok\nX"))
	for _, args := range [][]string{
		nil, {}, {""}, {"nft_ruleset", "extra"}, {"audit_rules", "nft_ruleset"}, {"/bin/sh"}, {"NFT_RULESET"},
		{"nft_ruleset\n"}, {"nft_ruleset "}, {"--serve"}, {"--serve", "x"}, {"../nft_ruleset"}, {"/usr/sbin/nft"},
		{"unknown_request"}, {"nft_ruleset;id"},
	} {
		code, out, errb := runClient(args, h.path)
		if code != 2 || out != "" || errb != "bitscan-capread: usage: bitscan-capread nft_ruleset|audit_rules|apparmor_profiles\n" {
			t.Errorf("%q: exit %d stdout %q stderr %q, want 2 and the usage line", args, code, out, errb)
		}
	}
	time.Sleep(200 * time.Millisecond)
	if n := h.conns.Load(); n != 0 {
		t.Fatalf("%d connections for refused arguments, want 0", n)
	}
}

// CHK-M10-176: only the request name and a newline are sent.
func TestClientSendsOnlyTheName(t *testing.T) {
	for _, name := range []string{"nft_ruleset", "audit_rules"} {
		h := helper(t, reply("ok\nrules"))
		code, out, errb := runClient([]string{name}, h.path)
		if code != 0 || out != "rules" || errb != "" {
			t.Fatalf("%s: exit %d stdout %q stderr %q", name, code, out, errb)
		}
		deadline := time.Now().Add(5 * time.Second)
		for {
			h.mu.Lock()
			n := len(h.got)
			h.mu.Unlock()
			if n == 1 || time.Now().After(deadline) {
				break
			}
			time.Sleep(10 * time.Millisecond)
		}
		h.mu.Lock()
		got := h.got
		h.mu.Unlock()
		// reply() consumed the first read (the request line); what came
		// after it is in got[0] and must be empty.
		if len(got) != 1 || len(got[0]) != 0 {
			t.Fatalf("%s: the client sent more after its request: %q", name, got)
		}
	}
	// The request line itself, byte for byte.
	var mu sync.Mutex
	var line []byte
	h := helper(t, func(c net.Conn) {
		_ = c.SetReadDeadline(time.Now().Add(5 * time.Second))
		b := make([]byte, 64)
		n, _ := io.ReadAtLeast(c, b, 1)
		mu.Lock()
		line = append([]byte(nil), b[:n]...)
		mu.Unlock()
		_, _ = io.WriteString(c, "ok\n")
	})
	if code, _, errb := runClient([]string{"audit_rules"}, h.path); code != 0 {
		t.Fatalf("exit %d %q", code, errb)
	}
	mu.Lock()
	defer mu.Unlock()
	if string(line) != "audit_rules\n" {
		t.Fatalf("request bytes %q, want exactly \"audit_rules\\n\"", line)
	}
}

// CHK-M10-176: the output is copied byte for byte (binary-safe, 1 MiB); more
// than 1 MiB is too_large with nothing printed.
func TestClientCopiesOutput(t *testing.T) {
	full := make([]byte, maxAnswer)
	for i := range full {
		full[i] = byte(i * 7)
	}
	h := helper(t, reply("ok\n"+string(full)))
	code, out, errb := runClient([]string{"nft_ruleset"}, h.path)
	if code != 0 || out != string(full) || errb != "" {
		t.Fatalf("1 MiB: exit %d, %d bytes equal %v, stderr %q", code, len(out), out == string(full), errb)
	}
	h2 := helper(t, reply("ok\n"+string(full)+"x"))
	code, out, errb = runClient([]string{"nft_ruleset"}, h2.path)
	if code != 1 || out != "" || errb != "bitscan-capread: too_large\n" {
		t.Fatalf("1 MiB + 1: exit %d, %d bytes out, stderr %q", code, len(out), errb)
	}
	h3 := helper(t, reply("ok\n"))
	if code, out, errb := runClient([]string{"audit_rules"}, h3.path); code != 0 || out != "" || errb != "" {
		t.Fatalf("empty output: exit %d %q %q", code, out, errb)
	}
}

// CHK-M10-176 and decisions "TASK-226 … accepted": an error answer is one
// stderr line `bitscan-capread: <word>`, exit 1; a word outside
// [a-z0-9_ ]{1,40} prints "bad answer"; nothing on stdout.
func TestClientErrorWords(t *testing.T) {
	cases := []struct{ answer, want string }{
		{"error timeout\n", "timeout"},
		{"error not_installed\n", "not_installed"},
		{"error unknown_request\n", "unknown_request"},
		{"error too_large\n", "too_large"},
		{"error failed 126\n", "failed 126"},
		{"error " + strings.Repeat("a", 40) + "\n", strings.Repeat("a", 40)},
		{"error " + strings.Repeat("a", 41) + "\n", "bad answer"},
		{"error \n", "bad answer"},
		{"error Timeout\n", "bad answer"},
		{"error a-b\n", "bad answer"},
		{"error a;b\n", "bad answer"},
		{"error a\tb\n", "bad answer"},
		{"error a\x1b[2Jb\n", "bad answer"},
		{"error a\rb\n", "bad answer"},
		{"error é\n", "bad answer"},
		{"error\n", "bad answer"},
		{"oops\n", "bad answer"},
		{"OK\n", "bad answer"},
		{"ok \n", "bad answer"},
		{strings.Repeat("e", 80) + "\n", "bad answer"},
		{"", "no answer"},
		{"ok", "no answer"},
		{"error timeout", "no answer"},
	}
	for _, tc := range cases {
		h := helper(t, reply(tc.answer))
		code, out, errb := runClient([]string{"nft_ruleset"}, h.path)
		if code != 1 || out != "" || errb != "bitscan-capread: "+tc.want+"\n" {
			t.Errorf("answer %q: exit %d stdout %q stderr %q, want 1 and %q", tc.answer, code, out, errb, tc.want)
		}
	}
}

// REQ-253 (3) at unit level: no socket → `not enabled`, exit 1.
func TestClientNotEnabled(t *testing.T) {
	code, out, errb := runClient([]string{"nft_ruleset"}, filepath.Join(t.TempDir(), "absent.sock"))
	if code != 1 || out != "" || errb != "bitscan-capread: not enabled\n" {
		t.Fatalf("exit %d stdout %q stderr %q", code, out, errb)
	}
	if Socket != "/run/bitscan/capread.sock" {
		t.Fatalf("Socket %q, want /run/bitscan/capread.sock (TS §3.7)", Socket)
	}
}

// CHK-M10-176: 30 s without an answer → `timeout`, exit 1; an answer that
// stalls mid-stream prints nothing (decisions "TASK-226": buffered, printed
// only after a clean end).
func TestClientNoAnswerTimeout(t *testing.T) {
	if clientTimeout != 30*time.Second {
		t.Fatalf("clientTimeout %v, want 30 s (#142 (f))", clientTimeout)
	}
	for _, tc := range []struct {
		name   string
		answer func(net.Conn)
	}{
		{"silent", func(net.Conn) { time.Sleep(45 * time.Second) }},
		{"stalls mid-stream", func(c net.Conn) {
			reply("ok\n" + strings.Repeat("partial ruleset ", 4096))(c)
			time.Sleep(45 * time.Second)
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			h := helper(t, tc.answer)
			start := time.Now()
			code, out, errb := runClient([]string{"nft_ruleset"}, h.path)
			d := time.Since(start)
			if code != 1 || out != "" || errb != "bitscan-capread: timeout\n" || d < 29*time.Second || d > 35*time.Second {
				t.Fatalf("after %v: exit %d, %d bytes out, stderr %q; want 1, nothing, timeout at 30 s", d, code, len(out), errb)
			}
		})
	}
}
