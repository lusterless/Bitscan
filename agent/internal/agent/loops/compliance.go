package loops

import (
	"context"
	"errors"
	"strings"

	"bitscan.local/agent/internal/agent/runnerclient"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
	"bitscan.local/agent/internal/spool"
)

// RunnerClient hands one whole job to the runner; *runnerclient.Client.
type RunnerClient interface {
	Run(ctx context.Context, job wire.Job, maxParallel int, onResult func(proto.Result) error) error
}

// Compliance is the compliance job handler (REQ-245; TS §3.5 L248–L252,
// §3.7 L282; #131). It records the job in the spool, passes the whole job to
// the runner, and spools each result as it arrives. It never executes,
// keeps or logs a plugin command, and never judges PASS/FAIL. The job value
// is dropped when Handle returns.
type Compliance struct {
	Run    *Run
	Spool  *spool.Spool
	Sender *Sender
	Runner RunnerClient
}

// Handle runs one accepted compliance job. When the runner is unavailable,
// every plugin without a result is spooled as runner_unavailable and the job
// is finished; it is never resent (#131 (b)). When the agent stops mid-job
// the job is left unfinished, so no final batch is ever sent for it (#131
// (d)); the spool marks it interrupted at the next start.
func (c *Compliance) Handle(ctx context.Context, job wire.Job) {
	r := c.Run
	ids := make([]wire.UUID, len(job.Plugins))
	for i, p := range job.Plugins {
		ids[i] = p.PluginUUID
	}
	if err := c.Spool.StartJob(job.JobID, ids); err != nil {
		r.Log().Error("the compliance job could not be recorded in the spool; not run", "job_id", string(job.JobID))
		r.SetLastError("spool: compliance job not recorded")
		return
	}
	c.Sender.Wake() // the start notice (TS §3.3 L222)
	got := make(map[wire.UUID]bool, len(ids))
	err := c.Runner.Run(ctx, job, r.MaxParallelPlugins(), func(res proto.Result) error {
		if err := c.Spool.Put(job.JobID, res); err != nil {
			return err
		}
		got[lowerID(res.Item().PluginUUID)] = true
		c.Sender.Wake()
		return nil
	})
	if ctx.Err() != nil {
		return
	}
	var f *runnerclient.Failure
	switch {
	case errors.As(err, &f):
		r.Log().Warn("the runner is unavailable; plugins without a result are reported runner_unavailable", "job_id", string(job.JobID), "reason", f.Word)
		r.SetLastError("runner_unavailable: " + f.Word)
		c.fill(job.JobID, ids, got, false)
	case err != nil: // a result could not be spooled (TASK-223 r1)
		r.Log().Warn("a result could not be spooled; plugins without a stored result are reported spool_overflow", "job_id", string(job.JobID))
		c.fill(job.JobID, ids, got, true)
	}
	if c.Spool.Finish(job.JobID) != nil {
		r.Log().Error("the compliance job could not be marked finished in the spool", "job_id", string(job.JobID))
	}
	c.Sender.Wake()
}

// fill stores an error item for every plugin without a stored result:
// runner_unavailable (#131 (b)), or spool_overflow when overflow is set.
// After any Put error the rest become spool_overflow markers; plugins whose
// marker cannot be stored either are counted, logged and set as last_error.
func (c *Compliance) fill(jobID wire.UUID, ids []wire.UUID, got map[wire.UUID]bool, overflow bool) {
	now := c.Run.Clock().Now()
	lost := 0
	for _, id := range ids {
		id = lowerID(id)
		if got[id] {
			continue
		}
		item := proto.UnavailableResult(id, now)
		if !overflow {
			if c.Spool.Put(jobID, item) == nil {
				got[id] = true
				continue
			}
			overflow = true
		}
		if c.Spool.Put(jobID, proto.OverflowMarker(item)) != nil {
			lost++
			continue
		}
		got[id] = true
	}
	if lost > 0 {
		c.Run.Log().Error("results could not be spooled, not even as markers", "job_id", string(jobID), "count", lost)
		c.Run.SetLastError("spool: results not kept")
	}
	c.Sender.Wake()
}

func lowerID(u wire.UUID) wire.UUID { return wire.UUID(strings.ToLower(string(u))) }
