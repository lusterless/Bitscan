//go:build linux

package runner

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/redact"
	"bitscan.local/agent/internal/runner/proto"
)

// captureGrace bounds the wait for a plugin's pipes to reach EOF once its
// cgroup is empty: a process that moved itself out of the cgroup may still
// hold them; the read ends are then closed and the after-job sweep kills it.
const captureGrace = time.Second

// JobExecutor is the Executor of TASK-224 (plan TASK-215 §6).
type JobExecutor struct {
	CG    *Cgroups
	Spawn func(*Plugin, string, func() time.Time) (*Spawned, error)
	Now   func() time.Time
	// TmpDirs are emptied after every job (#135 (c)): the runner's private
	// /tmp and /var/tmp in production; never a shared directory.
	TmpDirs []string
	Log     *slog.Logger
	redMu   sync.Mutex // one plugin redacted at a time (#134 (h))
}

// Run starts the plugins in payload order, at most MaxParallelPlugins at
// once, and emits one result per plugin as each finishes. A cgroup failure
// stops new starts: those plugins are emitted runner_unavailable (#136 (f)).
// When ctx is cancelled it kills the running plugins and emits nothing more.
// Always, before returning: the sweep and the emptying of TmpDirs; their
// failure is the only error Run returns (fatal, the runner exits).
func (e *JobExecutor) Run(ctx context.Context, req proto.Request, emit func(proto.Result) error) error {
	set, err := redact.Compile(req.Job.RedactionPatterns)
	plugins := req.Job.Plugins
	var stopped atomic.Bool
	started := 0
	if err == nil {
		sem := make(chan struct{}, req.MaxParallelPlugins)
		var wg sync.WaitGroup
	start:
		for _, p := range plugins {
			select {
			case sem <- struct{}{}:
			case <-ctx.Done():
				break start
			}
			if ctx.Err() != nil || stopped.Load() {
				break
			}
			started++
			wg.Add(1)
			go func() {
				defer wg.Done()
				defer func() { <-sem }()
				e.plugin(ctx, req.Job.JobID, set, p, &stopped, emit)
			}()
		}
		wg.Wait()
	}
	for _, p := range plugins[started:] {
		e.unavailable(ctx, p.PluginUUID, emit)
	}
	return e.cleanup(ctx)
}

func (e *JobExecutor) unavailable(ctx context.Context, id wire.UUID, emit func(proto.Result) error) {
	if ctx.Err() == nil {
		_ = emit(proto.UnavailableResult(id, e.Now()))
	}
}

// plugin runs one plugin: cgroup, start, capture, timeout, kill, wait empty,
// remove, temp directory, then redaction and emit.
func (e *JobExecutor) plugin(ctx context.Context, job wire.UUID, set *redact.Set, p wire.PluginSpec, stopped *atomic.Bool, emit func(proto.Result) error) {
	cg, err := e.CG.NewPlugin()
	if err != nil {
		stopped.Store(true)
		e.unavailable(ctx, p.PluginUUID, emit)
		return
	}
	s, err := e.Spawn(cg, p.Execute, e.Now)
	if errors.Is(err, ErrCgroup) {
		stopped.Store(true)
	}
	if s == nil {
		e.release(ctx, cg)
		e.unavailable(ctx, p.PluginUUID, emit)
		return
	}
	// stop kills the cgroup and then always the shell itself: a shell that
	// moved out of p-<n> (TS §3.7 L284) survives cgroup.kill, and the wait
	// below would block on it forever (TASK-224 r1). The sweep gets the rest.
	// Kill is safe beside the concurrent Wait (pidfd, or os.Process's sigMu
	// in PID mode); after the reap it returns os.ErrProcessDone, ignored.
	stop := func() {
		_ = cg.Kill()
		_ = s.proc.Kill()
	}
	if err != nil {
		stop() // started, but the cgroup state is broken: reported unavailable
	}
	var out, errOut redact.Captured
	var outErr, errOutErr error
	var capWG sync.WaitGroup
	capWG.Add(2)
	go func() { defer capWG.Done(); out, outErr = Capture(s.Stdout) }()
	go func() { defer capWG.Done(); errOut, errOutErr = Capture(s.Stderr) }()
	type waited struct {
		exit int64
		err  error
	}
	waitCh := make(chan waited, 1)
	go func() { ws, err := s.Wait(); waitCh <- waited{ExitCode(ws), err} }()
	timer := time.NewTimer(time.Duration(p.TimeoutS) * time.Second)
	defer timer.Stop()
	timedOut := false
	var w waited
	select {
	case w = <-waitCh:
	case <-timer.C:
		timedOut = true
		stop()
		w = <-waitCh
	case <-ctx.Done():
		stop()
		w = <-waitCh
	}
	finished := e.Now()
	// Every process left in the cgroup is killed (TS §3.5 L250).
	e.release(ctx, cg)
	capDone := make(chan struct{})
	go func() { capWG.Wait(); close(capDone) }()
	select {
	case <-capDone:
	case <-time.After(captureGrace):
	}
	_, _ = s.Stdout.Close(), s.Stderr.Close()
	<-capDone
	// A stream cut short by a read error, including the read ends closed
	// just above, is never sent as whole: either error sets the one
	// truncated flag, through stdout's Overflow (stdout-driven, #113), so the
	// evaluator answers ERROR. A stderr cap cut alone still never sets it.
	if outErr != nil || errOutErr != nil {
		out.Overflow = true
	}
	// The same for a plugin that ran while the shared task limit refused a
	// fork: a process it needed may never have started.
	if cg.HitTaskLimit() {
		out.Overflow = true
		e.Log.Warn("runner: the plugins task limit was hit while the plugin ran; reported truncated",
			"job_id", string(job), "plugin_uuid", string(p.PluginUUID))
	}
	_ = RemoveTempDir(s.TempDir)
	if ctx.Err() != nil {
		return
	}
	if err != nil || w.err != nil {
		e.unavailable(ctx, p.PluginUUID, emit)
		return
	}
	e.redMu.Lock()
	res := Build(set, Outcome{Plugin: p.PluginUUID, Started: s.Started, Finished: finished,
		Stdout: out, Stderr: errOut, Exit: w.exit, TimedOut: timedOut})
	e.redMu.Unlock()
	e.Log.Info("runner: plugin done", "job_id", string(job), "plugin_uuid", string(p.PluginUUID),
		"exit_code", w.exit, "timed_out", timedOut, "duration_ms", finished.Sub(s.Started).Milliseconds())
	_ = emit(res)
}

// release kills the plugin cgroup, waits for it to empty and removes it. A
// cgroup that does not empty is left to the after-job sweep.
func (e *JobExecutor) release(ctx context.Context, cg *Plugin) {
	if err := cg.Kill(); err != nil {
		e.Log.Error("runner: plugin cgroup kill failed")
		return
	}
	if err := cg.WaitEmpty(context.WithoutCancel(ctx)); err != nil {
		e.Log.Error("runner: plugin cgroup not empty, left to the sweep")
		return
	}
	_ = cg.Remove()
}

// cleanup is the after-job step, also after a cancel: the subtree sweep,
// then every entry of TmpDirs removed (#135 (c), #138 (a)).
func (e *JobExecutor) cleanup(ctx context.Context) error {
	errs := []error{e.CG.Sweep(context.WithoutCancel(ctx))}
	for _, dir := range e.TmpDirs {
		entries, err := os.ReadDir(dir)
		errs = append(errs, err)
		for _, ent := range entries {
			errs = append(errs, RemoveTempDir(filepath.Join(dir, ent.Name())))
		}
	}
	if err := errors.Join(errs...); err != nil {
		e.Log.Error("runner: after-job cleanup failed")
		return err
	}
	return nil
}
