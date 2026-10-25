package inventory

import (
	"encoding/binary"
	"errors"
	"fmt"
	"os"
	"strings"
	"syscall"
)

func init() { openWatch = openInotify }

// inotifyWatch watches one directory for IN_MOVED_TO and IN_CLOSE_WRITE on
// the name "status" (TS §3.4 L239), with the standard library's syscall only.
type inotifyWatch struct {
	f   *os.File // non-blocking fd in Go's poller, so Close unblocks Read
	buf []byte
}

func openInotify(dir string) (dirWatch, error) {
	fd, err := syscall.InotifyInit1(syscall.IN_CLOEXEC | syscall.IN_NONBLOCK)
	if err != nil {
		return nil, fmt.Errorf("inventory: inotify_init1: %w", err)
	}
	// IN_ONLYDIR: a watch on a file would never name "status", so the kernel
	// must refuse anything but a directory (ENOTDIR), in the same call.
	if _, err := syscall.InotifyAddWatch(fd, dir, syscall.IN_MOVED_TO|syscall.IN_CLOSE_WRITE|syscall.IN_ONLYDIR); err != nil {
		_ = syscall.Close(fd)
		return nil, fmt.Errorf("inventory: watch %s: %w", dir, err)
	}
	return &inotifyWatch{f: os.NewFile(uintptr(fd), "inotify"), buf: make([]byte, 64*1024)}, nil
}

func (w *inotifyWatch) Close() error { return w.f.Close() }

func (w *inotifyWatch) Wait() error {
	for {
		n, err := w.f.Read(w.buf)
		if err != nil {
			return fmt.Errorf("inventory: read inotify: %w", err)
		}
		changed, err := scanEvents(w.buf[:n])
		if err != nil {
			return err
		}
		if changed {
			return nil
		}
	}
}

// scanEvents reads a batch of inotify_event records. A queue overflow counts
// as a change (lead ruling 2026-10-24); a removed watch ends the watcher.
func scanEvents(b []byte) (bool, error) {
	changed := false
	for len(b) >= syscall.SizeofInotifyEvent {
		mask := binary.NativeEndian.Uint32(b[4:8])
		end := syscall.SizeofInotifyEvent + int(binary.NativeEndian.Uint32(b[12:16]))
		if end > len(b) {
			break
		}
		name := strings.TrimRight(string(b[syscall.SizeofInotifyEvent:end]), "\x00")
		switch {
		case mask&syscall.IN_Q_OVERFLOW != 0:
			changed = true
		case mask&syscall.IN_IGNORED != 0:
			return changed, errors.New("inventory: the dpkg directory watch was removed")
		case name == "status" && mask&(syscall.IN_MOVED_TO|syscall.IN_CLOSE_WRITE) != 0:
			changed = true
		}
		b = b[end:]
	}
	return changed, nil
}
