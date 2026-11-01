package runner

import (
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/redact"
	"bitscan.local/agent/internal/runner/proto"
)

// Outcome is what the executor knows about one finished plugin. Stdout and
// Stderr are raw; they never leave the runner except through Build.
type Outcome struct {
	Plugin   wire.UUID
	Started  time.Time // runner clock, just before the start
	Finished time.Time // runner clock, just after the wait
	Stdout   redact.Captured
	Stderr   redact.Captured
	Exit     int64 // ExitCode of the wait status
	TimedOut bool
}

// Build redacts both streams with set and returns the plugin's Results item
// (TS §3.5 L252; REQ-241): exit code, redacted and capped stdout and stderr,
// UTC start and end times, timed_out, truncated (stdout only, #113), error
// null. If the item does not pass proto.NewResult (a bug), the plugin is
// reported runner_unavailable instead: raw or over-cap text is never sent.
// A plugin that could not be started gets proto.UnavailableResult directly.
func Build(set *redact.Set, o Outcome) proto.Result {
	stdout, truncated := set.Apply(o.Stdout, redact.Stdout)
	stderr, _ := set.Apply(o.Stderr, redact.Stderr)
	finished := o.Finished
	if finished.Before(o.Started) {
		// A wall-clock step back must not give finished_at < started_at.
		finished = o.Started
	}
	exit := o.Exit
	r, err := proto.NewResult(wire.ResultItem{
		PluginUUID: o.Plugin,
		ExitCode:   &exit,
		Stdout:     stdout,
		Stderr:     stderr,
		StartedAt:  wire.NewTime(o.Started),
		FinishedAt: wire.NewTime(finished),
		TimedOut:   o.TimedOut,
		Truncated:  truncated,
	})
	if err != nil {
		return proto.UnavailableResult(o.Plugin, finished)
	}
	return r
}
