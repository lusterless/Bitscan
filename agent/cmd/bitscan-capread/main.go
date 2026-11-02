//go:build linux

// Command bitscan-capread is the optional read-only helper (TS §3.7
// L437–L484). With exactly one request name it is the client a plugin calls;
// with --serve it is the helper, started by bitscan-capread.socket. It is
// enabled only on the host itself; the manager never enables it.
package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"bitscan.local/agent/internal/capread"
	"bitscan.local/agent/internal/sdsock"
)

func main() {
	args := os.Args[1:]
	if len(args) == 1 && args[0] == "--serve" {
		os.Exit(serve())
	}
	os.Exit(capread.Client(args, capread.Socket, os.Stdout, os.Stderr))
}

// serve takes the socket from systemd (REQ-235) and answers peers with the
// uid of bitscan-runner only (TS §3.7 L484), until SIGTERM. A start-up
// refusal is one log line and exit 1.
func serve() int {
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	uid, err := sdsock.LookupUID("bitscan-runner")
	if err != nil {
		log.Error("the bitscan-runner user is not known; not serving")
		return 1
	}
	l, err := sdsock.FromSystemd(uid, log)
	if err != nil {
		log.Error("no usable socket from systemd; not serving", "reason", err.Error())
		return 1
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, os.Interrupt)
	defer stop()
	if err := capread.Serve(ctx, l, log); err != nil {
		log.Error("the helper stopped", "reason", err.Error())
		return 1
	}
	return 0
}
