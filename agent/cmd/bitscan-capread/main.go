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
	"runtime"
	"syscall"

	"bitscan.local/agent/internal/capread"
	"bitscan.local/agent/internal/sdsock"
)

func main() {
	args := os.Args[1:]
	if len(args) == 1 && args[0] == "--serve" {
		os.Exit(serve())
	}
	os.Exit(client(args, capread.Socket))
}

// client is the path a plugin runs: forward one request name to the helper.
//
// It first drops to one P. The client runs inside a plugin cgroup, under the
// runner's TasksMax=64 (TS §3.7), and every thread it starts counts against
// the runner's own tasks. The Go runtime sizes GOMAXPROCS from the client's
// own cgroup only: the runner copies its cpu.max into each plugin cgroup
// (internal/runner limitCPU), which gives 2, but without that copy it is the
// host's CPU count. A garbage collection then starts GOMAXPROCS/4 dedicated
// mark workers, each on its own thread (64 on a 256-CPU host), and the
// runner can no longer create threads. Reading a large answer triggers such
// a collection; with one P there are no dedicated workers, only a fractional
// one on the same P. The answer is at most 1 MiB, so one P is plenty. A
// collection that the runtime itself starts before main() (from about 250
// Ps) is out of the client's reach; the runner's copied limit prevents it.
func client(args []string, socket string) int {
	runtime.GOMAXPROCS(1)
	return capread.Client(args, socket, os.Stdout, os.Stderr)
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
