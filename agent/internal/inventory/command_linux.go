package inventory

import (
	"errors"
	"os"
	"os/exec"
	"syscall"
)

// Each command leads its own process group (pgid = its pid). The kill at the
// limit, and the sweep after Wait, signal the whole group, because
// exec.CommandContext and WaitDelay reach only the direct child (TASK-094
// TEST, CHK-M4-097). The group id stays reserved while any member is alive,
// so the sweep cannot hit an unrelated process.
func init() {
	isolate = func(cmd *exec.Cmd) {
		cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
		cmd.Cancel = func() error { return killGroup(cmd) }
	}
	reap = func(cmd *exec.Cmd) {
		if cmd.Process != nil {
			_ = killGroup(cmd)
		}
	}
}

func killGroup(cmd *exec.Cmd) error {
	err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	if errors.Is(err, syscall.ESRCH) {
		return os.ErrProcessDone
	}
	return err
}
