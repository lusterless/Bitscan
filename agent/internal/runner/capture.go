package runner

import (
	"bytes"
	"fmt"
	"io"
	"syscall"

	"bitscan.local/agent/internal/redact"
)

// Capture reads one plugin stream until EOF or a read error. The first
// redact.ReadLimit bytes are kept; the rest is read and discarded, so the
// writer never blocks on a full pipe (#134 (b)). On a read error the bytes
// kept so far are returned with it; they are raw and must only go to Build.
// The caller reads stdout and stderr in two goroutines, started before it
// waits for the process.
func Capture(r io.Reader) (redact.Captured, error) {
	var buf bytes.Buffer
	if _, err := buf.ReadFrom(io.LimitReader(r, redact.ReadLimit)); err != nil {
		return redact.Captured{Data: buf.Bytes()}, fmt.Errorf("runner: capture: %w", err)
	}
	extra, err := io.Copy(io.Discard, r)
	c := redact.Captured{Data: buf.Bytes(), Overflow: extra > 0}
	if err != nil {
		return c, fmt.Errorf("runner: capture: %w", err)
	}
	return c, nil
}

// ExitCode maps a wait status to the reported exit code (#114, #136 (e)): a
// process that exited gives its status, one killed by a signal gives 128 +
// the signal number (a timeout's SIGKILL gives 137), so no code is negative.
func ExitCode(ws syscall.WaitStatus) int64 {
	return exitCode(ws.Signaled(), ws.ExitStatus(), int(ws.Signal()))
}

// exitCode is ExitCode on plain values, so the mapping is testable where a
// signalled wait status cannot be built (Windows). wait(2) without WUNTRACED
// reports only an exit or a signal.
func exitCode(signaled bool, status, signal int) int64 {
	if signaled {
		return 128 + int64(signal)
	}
	return int64(status)
}
