// Package sdsock adopts the one listening Unix socket systemd passes as fd 3
// (bitscan-runner.socket, bitscan-capread.socket) and accepts only peers
// with one uid (SO_PEERCRED). It never creates, binds or listens on a
// socket (TS §2.2 L111, §3.7 L281–L283).
package sdsock

import (
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"strconv"

	"golang.org/x/sys/unix"
)

const listenFD = 3 // SD_LISTEN_FDS_START

// Listener is the adopted socket.
type Listener struct {
	ul        *net.UnixListener
	fd3       *os.File // kept open (close-on-exec), so fd 3 stays the socket
	expectUID uint32
	log       *slog.Logger
}

// FromSystemd first marks every inherited descriptor above 2 close-on-exec,
// so no plugin can inherit one (TS §3.7 L283). It then refuses unless
// LISTEN_PID is this process, LISTEN_FDS is 1 and fd 3 is a listening
// AF_UNIX stream socket, and adopts fd 3. Errors carry fixed words only.
func FromSystemd(expectUID uint32, log *slog.Logger) (*Listener, error) {
	if err := cloexecInherited(); err != nil {
		return nil, err
	}
	pid, err := strconv.Atoi(os.Getenv("LISTEN_PID"))
	if err != nil || pid != os.Getpid() {
		return nil, errors.New("sdsock: LISTEN_PID is not this process")
	}
	if os.Getenv("LISTEN_FDS") != "1" {
		return nil, errors.New("sdsock: LISTEN_FDS is not 1")
	}
	if err := checkListening(listenFD); err != nil {
		return nil, err
	}
	f := os.NewFile(listenFD, "systemd-socket")
	ln, err := net.FileListener(f)
	if err != nil {
		return nil, fmt.Errorf("sdsock: adopt fd 3: %w", err)
	}
	ul, ok := ln.(*net.UnixListener)
	if !ok {
		_ = ln.Close()
		return nil, errors.New("sdsock: fd 3 is not a Unix socket")
	}
	return &Listener{ul: ul, fd3: f, expectUID: expectUID, log: log}, nil
}

// Close closes the listener and fd 3.
func (l *Listener) Close() error { return errors.Join(l.ul.Close(), l.fd3.Close()) }

// cloexecInherited sets FD_CLOEXEC on every open descriptor above 2.
func cloexecInherited() error {
	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		return fmt.Errorf("sdsock: list descriptors: %w", err)
	}
	for _, e := range entries {
		fd, err := strconv.Atoi(e.Name())
		if err != nil || fd <= 2 {
			continue
		}
		flags, err := unix.FcntlInt(uintptr(fd), unix.F_GETFD, 0)
		if errors.Is(err, unix.EBADF) {
			continue // the directory's own descriptor, closed after the read
		}
		if err != nil {
			return fmt.Errorf("sdsock: F_GETFD: %w", err)
		}
		if _, err := unix.FcntlInt(uintptr(fd), unix.F_SETFD, flags|unix.FD_CLOEXEC); err != nil {
			return fmt.Errorf("sdsock: F_SETFD: %w", err)
		}
	}
	return nil
}

// checkListening refuses fd unless it is an AF_UNIX SOCK_STREAM socket in
// the listening state.
func checkListening(fd int) error {
	var st unix.Stat_t
	if err := unix.Fstat(fd, &st); err != nil || st.Mode&unix.S_IFMT != unix.S_IFSOCK {
		return errors.New("sdsock: fd 3 is not a socket")
	}
	for _, want := range []struct{ opt, val int }{
		{unix.SO_DOMAIN, unix.AF_UNIX},
		{unix.SO_TYPE, unix.SOCK_STREAM},
		{unix.SO_ACCEPTCONN, 1},
	} {
		v, err := unix.GetsockoptInt(fd, unix.SOL_SOCKET, want.opt)
		if err != nil || v != want.val {
			return errors.New("sdsock: fd 3 is not a listening Unix stream socket")
		}
	}
	return nil
}
