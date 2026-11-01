// TP-M10-14 client half, Linux rows (tester-m10c): an answer cut off by the
// connection ending abnormally prints nothing; a socket nobody listens on is
// `not enabled`.
package capread

import (
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

// The helper sends ok and part of a ruleset, then closes while the client's
// request is still unread, so the client's read ends in ECONNRESET after the
// partial data: nothing may be printed (decisions "TASK-226": a cut-off
// answer is never printed).
func TestClientCutOffAnswer(t *testing.T) {
	for range 20 {
		h := helper(t, func(c net.Conn) {
			time.Sleep(100 * time.Millisecond) // the request is now queued, unread
			_, _ = io.WriteString(c, "ok\n"+strings.Repeat("table inet filter { } ", 4000))
			_ = c.Close()
		})
		code, out, errb := runClient([]string{"nft_ruleset"}, h.path)
		if code == 0 || out != "" {
			t.Fatalf("cut-off answer: exit %d, %d bytes printed, stderr %q; want non-zero and nothing", code, len(out), errb)
		}
		if errb != "bitscan-capread: no answer\n" {
			t.Logf("RECORDED: stderr %q", errb)
		}
	}
}

func TestClientRefusedSocket(t *testing.T) {
	dir, err := os.MkdirTemp("", "cr")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = os.RemoveAll(dir) }()
	p := filepath.Join(dir, "c.sock")
	fd, err := syscall.Socket(syscall.AF_UNIX, syscall.SOCK_STREAM, 0)
	if err != nil {
		t.Fatal(err)
	}
	if err := syscall.Bind(fd, &syscall.SockaddrUnix{Name: p}); err != nil {
		t.Fatal(err)
	}
	_ = syscall.Close(fd) // bound, never listening: ECONNREFUSED
	code, out, errb := runClient([]string{"audit_rules"}, p)
	if code != 1 || out != "" || errb != "bitscan-capread: not enabled\n" {
		t.Fatalf("exit %d stdout %q stderr %q", code, out, errb)
	}
}
