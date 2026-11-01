//go:build linux

// Command bitscan-runner checks and runs whole compliance jobs that
// bitscan-agent hands over on the systemd socket /run/bitscan/runner.sock,
// and returns redacted results (TS §3.5, §3.7). It has no network client,
// opens no socket of its own, takes no command but a whole job, and holds
// no capability beyond CAP_DAC_READ_SEARCH.
package main

import (
	"context"
	"errors"
	"io/fs"
	"log/slog"
	"os"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	"bitscan.local/agent/internal/runner"
	"bitscan.local/agent/internal/sdsock"
)

// version is set by the build: -ldflags "-X main.version=<version>".
var version string

// peerUser is the only user the runner serves (TS §3.7 L282).
const peerUser = "bitscan"

// init locks the main goroutine to the main thread (m0) for the whole run.
// Spawn's goroutines lower their thread to nice 10 and I/O class idle; on
// m0 the runtime would park that thread rather than end it, leaving the
// runner's main thread lowered. Held by main, m0 never runs them, so each
// gets its own thread that ends with it (TS §3.5, #136 (b), TASK-221 r2).
func init() { runtime.LockOSThread() }

func main() { os.Exit(run()) }

// run returns the exit code: 1 for a start-up refusal (#137) or when the
// runner can no longer guarantee its cleanup, 0 after SIGTERM or SIGINT.
// systemd restarts it either way (Restart=always).
func run() int {
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	// First: non-dumpable before anything else (TS §3.7 L283, #137).
	if err := runner.Harden(); err != nil {
		return refuse(log, err)
	}
	if err := runner.CheckStartup(runner.SystemProbe()); err != nil {
		return refuse(log, err)
	}
	uid, err := sdsock.LookupUID(peerUser)
	if err != nil {
		return refuse(log, err)
	}
	ln, err := sdsock.FromSystemd(uid, log)
	if err != nil {
		return refuse(log, err)
	}
	defer func() { _ = ln.Close() }()
	cg, err := runner.Open(log)
	if err != nil {
		return refuse(log, err)
	}
	// The start-up sweep: nothing a previous instance started survives.
	if err := cg.Sweep(context.Background()); err != nil {
		log.Error("start-up refused", "reason", pathless(err))
		return 1
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, os.Interrupt)
	defer stop()
	srv := &runner.Server{
		Listener: ln,
		Checks:   runner.NewChecks(runner.AgentIDPath),
		Exec: &runner.JobExecutor{
			CG:      cg,
			Spawn:   runner.Spawn,
			Now:     time.Now,
			TmpDirs: []string{"/tmp", "/var/tmp"}, // private to the unit (PrivateTmp=yes)
			Log:     log,
		},
		Clock: time.Now,
		Log:   log,
	}
	log.Info("bitscan-runner started", "version", version)
	if err := srv.Serve(ctx); err != nil {
		log.Error("bitscan-runner stopping: cleanup cannot be guaranteed", "reason", pathless(err))
		return 1
	}
	// SIGTERM: the running job was cancelled and swept inside Serve; one
	// more sweep before exit.
	if err := cg.Sweep(context.Background()); err != nil {
		log.Error("bitscan-runner stopping: final sweep failed", "reason", pathless(err))
		return 1
	}
	log.Info("bitscan-runner stopped")
	return 0
}

// refuse logs one start-up refusal and returns exit code 1. These errors
// hold fixed words and the runner's own paths, never a job, pattern, output
// or a name a plugin chose; sweep errors go through pathless instead.
func refuse(log *slog.Logger, err error) int {
	log.Error("start-up refused", "reason", err.Error())
	return 1
}

// pathless describes a sweep or cleanup error without its text: that can
// name a file a plugin made under /tmp or a cgroup it created, which must
// not reach journald (TS §5.3, §8.4; TASK-224 r2). It gives the operation
// and errno of the first *fs.PathError, else the first errno, else fixed
// words.
func pathless(err error) string {
	var errno syscall.Errno
	var pe *fs.PathError
	switch {
	case errors.As(err, &pe) && errors.As(pe.Err, &errno):
		return pe.Op + ": " + errno.Error()
	case pe != nil:
		return pe.Op
	case errors.As(err, &errno):
		return errno.Error()
	}
	return "no errno"
}
