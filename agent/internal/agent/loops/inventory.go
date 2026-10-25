package loops

import (
	"context"
	"sync"
	"time"

	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/inventory"
)

// jobUploadWindow is how long a job's upload is retried after the job was
// received; after it the manager has failed the job (plan TASK-104).
const jobUploadWindow = 30 * time.Minute

// Collector builds one gzip InventoryBody (inventory.CollectBody in
// production). It takes no job, heartbeat or manager value (#35).
type Collector func(ctx context.Context) ([]byte, error)

// DpkgWatcher signals dpkg changes (*inventory.Watcher, TASK-091).
type DpkgWatcher interface {
	Run(ctx context.Context, out chan<- struct{}) error
}

// Inventory is the InventoryRunner: it collects and uploads inventory for
// jobs and for watcher signals (TS §3.4 L239–L240, #72, #80).
type Inventory struct {
	run      *Run
	collect  Collector
	jobMu    sync.Mutex // job uploads one at a time
	unschMu  sync.Mutex // unscheduled uploads one at a time
	lastUnsc time.Time  // last unscheduled upload answered with success
}

var _ InventoryRunner = (*Inventory)(nil)

func NewInventory(r *Run, collect Collector) *Inventory {
	return &Inventory{run: r, collect: collect}
}

// RunJob uploads with ?job_id=. Wait and Retry answers are retried with the
// back-off, with the same body, until jobUploadWindow after the call.
func (inv *Inventory) RunJob(ctx context.Context, jobID wire.UUID) {
	received := inv.run.Clock().Now()
	inv.jobMu.Lock()
	defer inv.jobMu.Unlock()
	body, ok := inv.body(ctx)
	if !ok {
		return
	}
	back := schedule.NewBackoff(inv.run.Rand())
	for {
		resp, _ := inv.run.Call(ctx, transport.Request{Op: transport.OpInventory, JobID: jobID, Body: body, Gzip: true})
		if resp.Class != transport.Wait && resp.Class != transport.Retry {
			return // Success; Drop and Stop are handled by Call
		}
		wait := back.Next()
		if inv.run.Clock().Now().Add(wait).After(received.Add(jobUploadWindow)) {
			inv.run.Log().Warn("inventory job upload not answered within 30 minutes; given up", "job_id", string(jobID))
			return
		}
		if schedule.Sleep(ctx, inv.run.Clock(), wait) != nil {
			return
		}
	}
}

// Unscheduled uploads without job_id (one watcher signal).
func (inv *Inventory) Unscheduled(ctx context.Context) { inv.unscheduled(ctx, nil) }

// Watch runs w and makes one unscheduled upload per signal until ctx ends.
// A watch that cannot be set or fails is logged once; job uploads do not
// depend on it (REQ-102 (4)).
func (inv *Inventory) Watch(ctx context.Context, w DpkgWatcher) {
	signals := make(chan struct{})
	done := make(chan struct{})
	go func() {
		defer close(done)
		if err := w.Run(ctx, signals); err != nil && ctx.Err() == nil {
			inv.run.Log().Warn("the dpkg watch could not be set or has stopped; scheduled inventory continues")
		}
	}()
	defer func() { <-done }()
	for {
		select {
		case <-ctx.Done():
			return
		case <-done:
			return
		case <-signals:
			inv.unscheduled(ctx, signals)
		}
	}
}

// unscheduled waits until 10 min 30 s after the last accepted unscheduled
// upload (#80, #72 (e)), then uploads; Wait and Retry answers are retried with
// the back-off. A signal arriving meanwhile makes the next attempt collect
// again, so the latest state is sent.
func (inv *Inventory) unscheduled(ctx context.Context, signals <-chan struct{}) {
	inv.unschMu.Lock()
	defer inv.unschMu.Unlock()
	clock := inv.run.Clock()
	back := schedule.NewBackoff(inv.run.Rand())
	var body []byte
	stale := true
	for {
		if !inv.lastUnsc.IsZero() {
			if hold := inv.lastUnsc.Add(inventory.HoldOff).Sub(clock.Now()); hold > 0 && !inv.sleep(ctx, hold, signals, &stale) {
				return
			}
		}
		if stale {
			var ok bool
			if body, ok = inv.body(ctx); !ok {
				return
			}
			stale = false
		}
		resp, _ := inv.run.Call(ctx, transport.Request{Op: transport.OpInventory, Body: body, Gzip: true})
		switch resp.Class {
		case transport.Success:
			inv.lastUnsc = clock.Now()
			return
		case transport.Wait, transport.Retry:
			if !inv.sleep(ctx, back.Next(), signals, &stale) {
				return
			}
		default:
			return // Drop and Stop are handled by Call
		}
	}
}

// sleep waits d on the run clock; a signal meanwhile marks the body stale.
// It returns false when ctx ended.
func (inv *Inventory) sleep(ctx context.Context, d time.Duration, signals <-chan struct{}, stale *bool) bool {
	timer := inv.run.Clock().After(d)
	for {
		select {
		case <-ctx.Done():
			return false
		case <-timer:
			return true
		case <-signals:
			*stale = true
		}
	}
}

// body collects one inventory body. A failure uploads nothing (lead ruling
// Q2) and is reported as last_error with a fixed reason.
func (inv *Inventory) body(ctx context.Context) ([]byte, bool) {
	body, err := inv.collect(ctx)
	if err != nil {
		if ctx.Err() == nil {
			inv.run.Log().Warn("inventory collection failed; nothing uploaded")
			inv.run.SetLastError("inventory collection failed")
		}
		return nil, false
	}
	return body, true
}
