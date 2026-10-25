package loops

import (
	"context"

	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

// maxBatch is the most results in one batch (TS §3.3 L223).
const maxBatch = 50

// work runs the jobs of one kind one at a time, in the order they were
// accepted, until the Run stops. A job must start before its pickup_by; it
// may finish after it (TS §3.3 L212).
func (p *Puller) work(jobs <-chan wire.Job, run func(wire.Job)) {
	r := p.Run
	for {
		select {
		case <-r.Context().Done():
			return
		case job := <-jobs:
			if !job.PickupBy.Time().After(r.Clock().Now()) {
				p.refuse(job, "pickup_by passed before the job could start")
				continue
			}
			run(job)
		}
	}
}

// compliance hands one compliance job to the handler, reporting it as the
// current job in the heartbeat meanwhile (#78 (c)).
func (p *Puller) compliance(job wire.Job) {
	id := job.JobID
	p.Run.SetCurrentJob(&id)
	defer p.Run.SetCurrentJob(nil)
	p.Compliance.Handle(p.Run.Context(), job)
}

// Unavailable is the 0.x compliance handler (#74, #28): it executes nothing,
// never contacts the runner, and answers every plugin with error
// runner_unavailable, in batches of at most 50, only the last one final (lead
// ruling 2026-10-24). The plugin commands are never read or kept.
type Unavailable struct{ Run *Run }

func (u Unavailable) Handle(ctx context.Context, job wire.Job) {
	now := wire.NewTime(u.Run.Clock().Now())
	reason := wire.ResultError("runner_unavailable")
	items := make([]wire.ResultItem, 0, len(job.Plugins))
	for _, pl := range job.Plugins {
		items = append(items, wire.ResultItem{
			PluginUUID: pl.PluginUUID, ExitCode: nil, Stdout: "", Stderr: "",
			StartedAt: now, FinishedAt: now, Error: &reason,
		})
	}
	for start := 0; start == 0 || start < len(items); start += maxBatch {
		batch := items[start:min(start+maxBatch, len(items))]
		final := start+maxBatch >= len(items)
		if !u.post(ctx, job.JobID, wire.ResultsRequest{Results: batch, Final: final}) {
			return // a dropped batch ends the job: the rest would be refused alike
		}
	}
}

// post sends one batch, retrying 403 pending_approval, 429, 5xx and network
// errors with the back-off. Run.Call logs a drop and keeps it as last_error
// and stops every loop on a 401. It reports whether the batch was accepted.
func (u Unavailable) post(ctx context.Context, jobID wire.UUID, batch wire.ResultsRequest) bool {
	r := u.Run
	body, err := wire.Encode(batch)
	if err != nil {
		r.Log().Error("the results batch failed the contract check; not sent", "job_id", string(jobID))
		r.SetLastError("results batch refused")
		return false
	}
	back := schedule.NewBackoff(r.Rand())
	for {
		resp, _ := r.Call(ctx, transport.Request{Op: transport.OpResults, JobID: jobID, Body: body})
		switch resp.Class {
		case transport.Success:
			var rr wire.ResultsResponse
			if wire.DecodeStrict(resp.Body, &rr) != nil {
				r.Log().Warn("the results answer failed the contract check; the batch counts as sent", "job_id", string(jobID))
			}
			return true
		case transport.Wait, transport.Retry:
			if schedule.Sleep(ctx, r.Clock(), back.Next()) != nil {
				return false
			}
		default:
			return false
		}
	}
}
