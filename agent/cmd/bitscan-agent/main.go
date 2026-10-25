// Command bitscan-agent is the network-facing agent (TS §3.1–§3.4): it
// enrols, heartbeats, pulls jobs and uploads inventory. It runs no plugin
// command, opens no listening socket and writes only its state directory.
package main

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"bitscan.local/agent/internal/agent/config"
	"bitscan.local/agent/internal/agent/enrol"
	"bitscan.local/agent/internal/agent/loops"
	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/token"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/inventory"
)

// version is set by the build: -ldflags "-X main.version=<version>" (TASK-102).
var version string

// shutdownGrace is how long in-flight calls get after SIGTERM (plan TASK-101).
const shutdownGrace = 5 * time.Second

func main() { os.Exit(run()) }

// run returns the exit code: 1 for a start-up refusal, 0 after SIGTERM or
// SIGINT. After a 401 or a refused enrolment it stays up idle until a signal,
// so a restart loop never resends to the manager (#81 (a)).
func run() int {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, os.Interrupt)
	defer stop()
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	if version == "" {
		log.Error("start-up refused: the binary was built without a version")
		return 1
	}
	cfg, err := config.Load(config.Path)
	if err != nil {
		return refuse(log, err)
	}
	var level slog.Level
	if level.UnmarshalText([]byte(cfg.LogLevel)) != nil {
		level = slog.LevelInfo
	}
	log = slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: level}))

	machineID, err := enrol.ReadMachineID(enrol.MachineIDPath)
	if err != nil {
		return refuse(log, err)
	}
	tlsCfg, err := transport.NewTLSConfig(cfg.CAFile, cfg.ManagerSPKISHA256, "")
	if err != nil {
		return refuse(log, err)
	}
	client, err := transport.NewClient(cfg.ManagerURL, tlsCfg, machineID)
	if err != nil {
		return refuse(log, err)
	}
	store, err := state.Open(cfg.StateDir)
	if err != nil {
		return refuse(log, err)
	}
	defer func() { _ = store.Close() }()
	clock := schedule.RealClock{}
	seen, err := store.LoadSeen(clock.Now)
	if err != nil {
		return refuse(log, err)
	}

	enroller := &enrol.Enroller{Client: client, Store: store, MachineID: machineID, AgentVersion: version, Clock: clock}
	res, err := enroller.Start(ctx)
	switch {
	case ctx.Err() != nil:
		return 0
	case errors.Is(err, enrol.ErrNoCredentials):
		return refuse(log, err)
	case err != nil:
		log.Error("enrolment did not complete; the agent stays idle until it is restarted", "reason", err.Error())
		<-ctx.Done()
		return 0
	}

	holder := token.NewHolder(res.Token)
	r := loops.NewRun(ctx, loops.Deps{
		Client:             client,
		Tokens:             holder,
		Rotator:            token.NewRotator(client, store, holder, res.AgentID),
		AgentID:            res.AgentID,
		Version:            version,
		Clock:              clock,
		Rand:               schedule.CryptoSource{},
		Log:                log,
		JobPullSeconds:     cfg.JobPullSeconds,
		MaxParallelPlugins: cfg.MaxParallelPlugins,
	})
	inv := loops.NewInventory(r, inventory.CollectBody)
	var wg sync.WaitGroup
	wg.Go(r.Heartbeat)
	wg.Go((&loops.Puller{Run: r, Seen: seen, Inventory: inv}).Loop)
	wg.Go(func() { inv.Watch(r.Context(), inventory.NewWatcher(inventory.DpkgDir, clock)) })
	log.Info("bitscan-agent started", "version", version, "agent_id", string(res.AgentID))

	<-ctx.Done() // a 401 stops the loops but not the process (#81 (a))
	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(shutdownGrace):
		log.Warn("shutdown: work still in flight after 5 s; exiting")
	}
	return 0
}

// refuse logs one start-up refusal and returns exit code 1. The error texts
// of these packages are fixed and never hold a token or a body.
func refuse(log *slog.Logger, err error) int {
	log.Error("start-up refused", "reason", err.Error())
	return 1
}
