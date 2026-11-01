package runner

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"runtime"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

// The plugin process (TS §3.5 L249; #135, #136). This is the only file of
// the runner that starts a process.
const (
	shell    = "/bin/sh"
	pathEnv  = "PATH=/usr/sbin:/usr/bin:/sbin:/bin"
	tmpRoot  = "/tmp"
	niceness = 10
	// ioprio_set(2): IOPRIO_WHO_PROCESS, class idle (ionice -c3).
	ioprioWhoProcess = 1
	ioprioIdle       = 3 << 13
)

var (
	// ErrExec: this plugin could not be started; it is reported
	// runner_unavailable and the job goes on.
	ErrExec = errors.New("runner: plugin not started")
	// ErrCgroup: the plugin cgroup could not be entered or left; the job
	// stops (#136 (f)). If Spawn also returns a Spawned, the child runs and
	// the caller must kill its cgroup.
	ErrCgroup = errors.New("runner: plugin cgroup failed")
)

// Spawned is a started plugin. Stdout and Stderr are the read ends of its
// pipes; they reach EOF once every process holding the write ends is gone.
type Spawned struct {
	Stdout  *os.File
	Stderr  *os.File
	Started time.Time
	TempDir string
	proc    *os.Process
}

// Wait reaps the plugin's shell. It does not touch the pipes.
func (s *Spawned) Wait() (syscall.WaitStatus, error) {
	st, err := s.proc.Wait()
	if err != nil {
		return 0, fmt.Errorf("runner: wait: %w", err)
	}
	ws, ok := st.Sys().(syscall.WaitStatus)
	if !ok {
		return 0, errors.New("runner: wait: no wait status")
	}
	return ws, nil
}

// Spawn starts /bin/sh -c execute born in p's cgroup, with exactly the PATH
// variable, stdin /dev/null, stdout and stderr pipes and no other
// descriptor, a fresh 0700 working directory under the private /tmp (no
// TMPDIR), niceness 10 and I/O class idle. No Pdeathsig: it would fire when
// the start thread is discarded (#136 (c)).
func Spawn(p *Plugin, execute string, now func() time.Time) (*Spawned, error) {
	dir, err := os.MkdirTemp(tmpRoot, "bitscan-p-")
	if err != nil {
		return nil, fmt.Errorf("%w: temp dir: %w", ErrExec, err)
	}
	var files []*os.File
	cleanup := func() {
		for _, f := range files {
			_ = f.Close()
		}
		_ = RemoveTempDir(dir)
	}
	devnull, err := os.Open(os.DevNull)
	if err != nil {
		cleanup()
		return nil, fmt.Errorf("%w: /dev/null: %w", ErrExec, err)
	}
	files = append(files, devnull)
	outR, outW, err1 := os.Pipe()
	if err1 == nil {
		files = append(files, outR, outW)
	}
	errR, errW, err2 := os.Pipe()
	if err2 == nil {
		files = append(files, errR, errW)
	}
	if err := errors.Join(err1, err2); err != nil {
		cleanup()
		return nil, fmt.Errorf("%w: pipes: %w", ErrExec, err)
	}
	cmd := &exec.Cmd{
		Path:   shell,
		Args:   []string{shell, "-c", execute},
		Env:    []string{pathEnv},
		Dir:    dir,
		Stdin:  devnull,
		Stdout: outW,
		Stderr: errW,
	}
	type result struct {
		started         time.Time
		cgErr, startErr error
	}
	ch := make(chan result, 1)
	go func() {
		// Never unlocked: the thread ends with this goroutine, so no other
		// goroutine ever runs at niceness 10 or I/O class idle (#136 (b)).
		// That holds because this is never the main thread (m0), which the
		// runtime parks rather than ends: bitscan-runner's init locks m0 to
		// its main goroutine (TASK-221 r2).
		runtime.LockOSThread()
		var r result
		if r.startErr = lowerPriority(); r.startErr == nil {
			r.started = now()
			r.cgErr = p.StartIn(func() error { r.startErr = cmd.Start(); return nil })
		}
		ch <- r
	}()
	r := <-ch
	_, _, _ = devnull.Close(), outW.Close(), errW.Close()
	if cmd.Process != nil {
		s := &Spawned{Stdout: outR, Stderr: errR, Started: r.started, TempDir: dir, proc: cmd.Process}
		if r.cgErr != nil {
			return s, fmt.Errorf("%w: %w", ErrCgroup, r.cgErr)
		}
		return s, nil
	}
	cleanup()
	if r.cgErr != nil {
		return nil, fmt.Errorf("%w: %w", ErrCgroup, r.cgErr)
	}
	return nil, fmt.Errorf("%w: %w", ErrExec, r.startErr)
}

// lowerPriority sets this OS thread's niceness and I/O class; a child
// started from it inherits both. Either failing means no start (fail
// closed, never a plugin at normal priority).
func lowerPriority() error {
	tid := unix.Gettid()
	if err := unix.Setpriority(unix.PRIO_PROCESS, tid, niceness); err != nil {
		return fmt.Errorf("setpriority: %w", err)
	}
	if _, _, errno := unix.Syscall(unix.SYS_IOPRIO_SET, ioprioWhoProcess, uintptr(tid), ioprioIdle); errno != 0 {
		return fmt.Errorf("ioprio_set: %w", errno)
	}
	return nil
}

// RemoveTempDir deletes dir and everything in it without following
// symlinks. A directory a plugin made unwritable (it is the runner's own
// uid) is made 0700 again, and the removal retried. The chmods go through
// an os.Root on dir, so a symlink swapped in by a plugin still running
// cannot point them outside the tree (TASK-221 r1).
func RemoveTempDir(dir string) error {
	if os.RemoveAll(dir) == nil {
		return nil
	}
	if root, err := os.OpenRoot(dir); err == nil {
		_ = fs.WalkDir(root.FS(), ".", func(name string, d fs.DirEntry, err error) error {
			if err == nil && d.IsDir() {
				// A directory needs its x bit to be entered: 0700, owner only.
				_ = root.Chmod(name, 0o700)
			}
			return nil
		})
		_ = root.Close()
	}
	if err := os.RemoveAll(dir); err != nil {
		return fmt.Errorf("runner: remove temp dir: %w", err)
	}
	return nil
}
