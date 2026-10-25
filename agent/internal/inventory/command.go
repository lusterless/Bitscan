package inventory

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"sync"
	"time"
)

// command is one entry of the fixed inventory command list (#35; TS §3.4
// L234–L235, L238). bitscan-agent executes nothing else: the argv is fixed
// here, runs without a shell, and no part of it comes from a job, a heartbeat
// or any manager answer. `uname -r -m` and `nproc` are read without exec.
type command struct {
	source string   // the raw.errors key for this source
	paths  []string // absolute; the first that exists is run
	args   []string
	limit  time.Duration
	maxOut int
}

// dpkgFormat is the TS §3.4 L235 format. The \t and \n are dpkg-query's own
// escapes, passed literally as the shell's single quotes would.
const dpkgFormat = `${Package}\t${Version}\t${Architecture}\t${Status}\t${Source}\t${Installed-Size}\n`

// The only commands bitscan-agent runs. They are variables only so that
// in-package tests can substitute a hanging or failing program.
var (
	hostnamectlCmd = command{
		source: "hostnamectl",
		paths:  []string{"/usr/bin/hostnamectl"},
		limit:  5 * time.Second,
		maxOut: 1 << 20,
	}
	ipAddrCmd = command{
		source: "ip_addr",
		paths:  []string{"/usr/sbin/ip", "/usr/bin/ip", "/sbin/ip", "/bin/ip"},
		args:   []string{"-j", "addr"},
		limit:  5 * time.Second,
		maxOut: 1 << 20,
	}
	dpkgQueryCmd = command{
		source: "dpkg_query",
		paths:  []string{"/usr/bin/dpkg-query"},
		args:   []string{"-W", "-f=" + dpkgFormat},
		limit:  60 * time.Second,
		maxOut: 16 << 20,
	}
)

// minimalEnv is the whole environment of every command: nothing is inherited.
var minimalEnv = []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C"}

// waitDelay bounds the wait for output pipes after a kill, so a child that
// inherited stdout cannot hold the collection past its limit.
const waitDelay = time.Second

// isolate runs a command in its own process group and makes the kill at its
// limit reach the whole group; reap kills what is left of the group once the
// command has ended, so no child of it outlives the call. command_linux.go
// sets both; elsewhere they do nothing.
var (
	isolate = func(*exec.Cmd) {}
	reap    = func(*exec.Cmd) {}
)

// Fixed failure reasons. They are the raw.errors values (#77 (e)) and never
// carry command output or error text from the host.
var (
	errNotFound = errors.New("not found")
	errTimedOut = errors.New("timed out")
	errTooLarge = errors.New("output too large")
	errFailed   = errors.New("failed")
)

// find returns the first existing path of c, a regular executable file.
func (c command) find() (string, error) {
	for _, p := range c.paths {
		if fi, err := os.Stat(p); err == nil && fi.Mode().IsRegular() && fi.Mode().Perm()&0o111 != 0 {
			return p, nil
		}
	}
	return "", errNotFound
}

// run executes c and returns its stdout. Stdin and stderr are /dev/null. The
// process is killed at its limit, or as soon as its output passes maxOut.
// When ctx itself ends, ctx's error is returned (wrapped) rather than a reason.
func (c command) run(ctx context.Context) ([]byte, error) {
	path, err := c.find()
	if err != nil {
		return nil, err
	}
	runCtx, cancel := context.WithTimeout(ctx, c.limit)
	defer cancel()
	out := &cappedBuffer{max: c.maxOut, overflow: cancel}
	cmd := exec.CommandContext(runCtx, path, c.args...)
	cmd.Env = minimalEnv
	cmd.Dir = "/"
	cmd.Stdout = out
	cmd.WaitDelay = waitDelay
	isolate(cmd)
	runErr := cmd.Run()
	reap(cmd)
	switch {
	case ctx.Err() != nil:
		return nil, fmt.Errorf("inventory: %s: %w", c.source, ctx.Err())
	case out.overflowed():
		return nil, errTooLarge
	case errors.Is(runCtx.Err(), context.DeadlineExceeded):
		return nil, errTimedOut
	case runErr != nil:
		return nil, errFailed
	}
	return out.bytes(), nil
}

// cappedBuffer keeps at most max bytes and calls overflow once when a write
// would pass it (which kills the process).
type cappedBuffer struct {
	mu       sync.Mutex
	buf      []byte
	max      int
	over     bool
	overflow func()
}

func (b *cappedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.over {
		return 0, errTooLarge
	}
	if len(b.buf)+len(p) > b.max {
		b.over = true
		b.overflow()
		return 0, errTooLarge
	}
	b.buf = append(b.buf, p...)
	return len(p), nil
}

func (b *cappedBuffer) overflowed() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.over
}

func (b *cappedBuffer) bytes() []byte {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf
}
