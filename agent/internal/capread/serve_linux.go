package capread

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"strconv"
	"syscall"
	"time"
)

const (
	maxRequest  = 32               // the name and its LF (#142 (a))
	readTimeout = 5 * time.Second  // to read the request
	runTimeout  = 10 * time.Second // per command (TS §3.7)
	maxOutput   = 1 << 20          // 1 MiB of stdout (#57)
)

// Reply words (#142 (b)); "failed <exit code>" is built in run.
const (
	wordUnknown      = "unknown_request"
	wordNotInstalled = "not_installed"
	wordTimeout      = "timeout"
	wordTooLarge     = "too_large"
)

var errUnknown = errors.New("capread: unknown request")

// readRequest reads one request: a known name and LF, nothing else, at most
// maxRequest bytes. errUnknown means the answer is "error unknown_request";
// any other error means the connection is closed without an answer.
func readRequest(r io.Reader) ([]string, error) {
	var buf [maxRequest + 1]byte
	n := 0
	for n < len(buf) {
		m, err := r.Read(buf[n:])
		n += m
		if i := bytes.IndexByte(buf[:n], '\n'); i >= 0 {
			argv, ok := commands[string(buf[:i])]
			if !ok || i != n-1 { // not a name, or bytes after the LF
				return nil, errUnknown
			}
			return argv, nil
		}
		if errors.Is(err, io.EOF) {
			return nil, errUnknown
		}
		if err != nil {
			return nil, fmt.Errorf("capread: read the request: %w", err)
		}
	}
	return nil, errUnknown // no LF within maxRequest bytes
}

// errorLine is the one-line refusal; the command's output never follows it.
func errorLine(word string) []byte { return []byte("error " + word + "\n") }

// Listener gives peer-checked connections; *sdsock.Listener, which accepts
// only the uid of bitscan-runner (TS §3.7 L493; REQ-235).
type Listener interface {
	Accept() (*net.UnixConn, error)
	Close() error
}

// Serve answers connections one after another, one request each (#142 (d)),
// until ctx ends. Each log line holds the request name and the outcome word
// only, never output.
func Serve(ctx context.Context, l Listener, log *slog.Logger) error {
	stop := context.AfterFunc(ctx, func() { _ = l.Close() })
	defer stop()
	for {
		c, err := l.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("capread: accept: %w", err)
		}
		serveOne(ctx, c, log)
		_ = c.Close()
	}
}

func serveOne(ctx context.Context, c *net.UnixConn, log *slog.Logger) {
	_ = c.SetDeadline(time.Now().Add(readTimeout))
	argv, err := readRequest(c)
	if errors.Is(err, errUnknown) {
		log.Warn("request refused", "result", wordUnknown)
		_, _ = c.Write(errorLine(wordUnknown))
		return
	}
	if err != nil {
		log.Warn("request not read; closed")
		return
	}
	out, word := run(ctx, argv)
	log.Info("request answered", "command", argv[0], "result", word)
	// The client waits at most 30 s; a client that stops reading is cut off
	// so the next request is not held up.
	_ = c.SetDeadline(time.Now().Add(runTimeout))
	if word != "ok" {
		_, _ = c.Write(errorLine(word))
		return
	}
	_, _ = c.Write(append([]byte("ok\n"), out...))
}

// capped keeps up to maxOutput bytes; one byte more cancels the command.
type capped struct {
	buf    []byte
	over   bool
	cancel context.CancelFunc
}

func (w *capped) Write(p []byte) (int, error) {
	if len(w.buf)+len(p) > maxOutput {
		w.over = true
		w.cancel()
		return 0, errors.New("capread: output over the cap")
	}
	w.buf = append(w.buf, p...)
	return len(p), nil
}

// run starts one table command by absolute path with an empty environment,
// stdin and stderr on /dev/null, in /, for at most runTimeout. It returns
// stdout and "ok", or a reply word; output over 1 MiB is never returned
// (#142 (c)).
func run(ctx context.Context, argv []string) ([]byte, string) {
	if _, err := os.Stat(argv[0]); errors.Is(err, fs.ErrNotExist) {
		return nil, wordNotInstalled
	}
	cctx, cancel := context.WithTimeout(ctx, runTimeout)
	defer cancel()
	out := &capped{cancel: cancel}
	cmd := exec.CommandContext(cctx, argv[0], argv[1:]...) // argv comes only from commands
	cmd.Env = []string{}                                   // empty, not inherited (nil would inherit)
	cmd.Dir = "/"
	cmd.Stdout = out
	cmd.WaitDelay = time.Second
	err := cmd.Run()
	var ee *exec.ExitError
	switch {
	case out.over:
		return nil, wordTooLarge
	case errors.Is(cctx.Err(), context.DeadlineExceeded):
		return nil, wordTimeout
	case errors.As(err, &ee):
		code := ee.ExitCode()
		if ws, ok := ee.Sys().(syscall.WaitStatus); ok && ws.Signaled() {
			code = 128 + int(ws.Signal())
		}
		return nil, "failed " + strconv.Itoa(code)
	case err != nil: // could not start, or stdout copy failed
		return nil, "failed 126"
	}
	return out.buf, "ok"
}
