package runner

import (
	"fmt"
	"log/slog"
	"os"
	"path/filepath"

	"golang.org/x/sys/unix"
)

const (
	cgroupMount = "/sys/fs/cgroup"
	selfCgroup  = "/proc/self/cgroup"
)

// Open finds the runner's own cgroup (the single "0::<path>" line of
// /proc/self/cgroup), opens it as an os.Root, and runs Setup (supervisor
// and the move). Any error means the runner refuses to start (#137). The
// caller runs Sweep next (the start-up sweep).
func Open(log *slog.Logger) (*Cgroups, error) {
	b, err := readSelfCgroup()
	if err != nil {
		return nil, fmt.Errorf("runner: read own cgroup: %w", err)
	}
	base, err := parseSelfCgroup(b)
	if err != nil {
		return nil, err
	}
	// The root handle is close-on-exec and kept for the process lifetime.
	root, err := os.OpenRoot(filepath.Join(cgroupMount, base))
	if err != nil {
		return nil, fmt.Errorf("runner: open own cgroup: %w", err)
	}
	c := NewCgroups(CgroupDeps{
		FS:         RootFS(root),
		Base:       base,
		Self:       os.Getpid(),
		SelfCgroup: readSelfCgroup,
		KillPid:    killPid,
		Log:        log,
	})
	if err := c.Setup(); err != nil {
		_ = root.Close()
		return nil, err
	}
	return c, nil
}

func readSelfCgroup() ([]byte, error) { return os.ReadFile(selfCgroup) }

// killPid pins pid with a pidfd before checking it is still in the swept
// cgroup, so a recycled pid is never signalled (#138 (a)).
func killPid(pid int, still func() bool) error {
	fd, err := unix.PidfdOpen(pid, 0)
	if err != nil {
		return fmt.Errorf("runner: pidfd_open: %w", err)
	}
	defer func() { _ = unix.Close(fd) }()
	if !still() {
		return nil
	}
	if err := unix.PidfdSendSignal(fd, unix.SIGKILL, nil, 0); err != nil {
		return fmt.Errorf("runner: pidfd_send_signal: %w", err)
	}
	return nil
}
