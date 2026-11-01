package sdsock

import (
	"errors"
	"fmt"
	"net"
	"os/user"
	"strconv"

	"golang.org/x/sys/unix"
)

// Accept returns the next connection whose peer uid (SO_PEERCRED) is the
// expected one. Any other peer, uid 0 included, is closed before a byte is
// read, with one log line naming its uid (TS §3.7 L282).
func (l *Listener) Accept() (*net.UnixConn, error) {
	for {
		c, err := l.ul.AcceptUnix()
		if err != nil {
			return nil, fmt.Errorf("sdsock: accept: %w", err)
		}
		uid, ok := peerUID(c)
		if ok && uid == l.expectUID {
			return c, nil
		}
		_ = c.Close()
		if ok {
			l.log.Warn("sdsock: peer refused", "uid", uid)
		} else {
			l.log.Warn("sdsock: peer refused, no credentials")
		}
	}
}

func peerUID(c *net.UnixConn) (uint32, bool) {
	raw, err := c.SyscallConn()
	if err != nil {
		return 0, false
	}
	var cred *unix.Ucred
	var credErr error
	if err := raw.Control(func(fd uintptr) {
		cred, credErr = unix.GetsockoptUcred(int(fd), unix.SOL_SOCKET, unix.SO_PEERCRED)
	}); err != nil || credErr != nil || cred == nil {
		return 0, false
	}
	return cred.Uid, true
}

// LookupUID finds a user's uid in /etc/passwd (os/user without CGO), for
// bitscan (the runner's peer) and bitscan-runner (capread's peer).
func LookupUID(name string) (uint32, error) {
	u, err := user.Lookup(name)
	if err != nil {
		return 0, fmt.Errorf("sdsock: look up user: %w", err)
	}
	uid, err := strconv.ParseUint(u.Uid, 10, 32)
	if err != nil {
		return 0, errors.New("sdsock: user has no numeric uid")
	}
	return uint32(uid), nil
}
