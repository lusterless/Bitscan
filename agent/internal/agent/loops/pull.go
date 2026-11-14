package loops

import (
	"strings"
	"sync"
	"time"

	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

// maxPickupAhead is the furthest pickup_by the agent accepts (TS §3.3 L212).
const maxPickupAhead = 25 * time.Hour

// Seen is the persisted set of job ids seen in the last 7 days; *state.Seen.
type Seen interface {
	Has(id wire.UUID) bool
	Add(id wire.UUID) error
}

// Puller is the job pull loop and its dispatch. Run, Seen and Inventory are
// required. A nil Compliance is refused: every compliance job is refused and
// logged, and inventory jobs still run (TS §1.1 G2).
type Puller struct {
	Run        *Run
	Seen       Seen
	Inventory  InventoryRunner
	Compliance ComplianceHandler
}

// Loop pulls once after the first heartbeat attempt, then every
// job_pull_seconds ± 30 s, until the Run stops (TS §3.3 L203). 403
// pending_approval, 429, 5xx and network errors use the back-off instead. An
// empty answer does nothing until the next timer (L216). Jobs come only from
// these answers. Loop returns once its workers have stopped.
func (p *Puller) Loop() {
	r := p.Run
	if p.Compliance == nil {
		r.Log().Error("no compliance handler: compliance jobs are refused; inventory is unaffected")
	}
	select {
	case <-r.FirstHeartbeat():
	case <-r.Context().Done():
		return
	}
	inv, comp := make(chan wire.Job, 10), make(chan wire.Job, 10)
	var wg sync.WaitGroup
	wg.Add(2)
	go func() { defer wg.Done(); p.work(inv, func(j wire.Job) { p.Inventory.RunJob(r.Context(), j.JobID) }) }()
	go func() { defer wg.Done(); p.pool(comp, p.compliance) }()
	defer wg.Wait()
	back := schedule.NewBackoff(r.Rand())
	for {
		var wait time.Duration
		follow := false
		switch p.pull(inv, comp) {
		case transport.Stop:
			return
		case transport.Wait, transport.Retry:
			wait = back.Next()
		default:
			back.Reset()
			wait, follow = r.PullInterval(), true
		}
		if !p.sleep(wait, follow) {
			return
		}
	}
}

// sleep waits d. With follow set, a new pull interval from a heartbeat
// restarts the wait from now with the new value; during a back-off it waits.
func (p *Puller) sleep(d time.Duration, follow bool) bool {
	r := p.Run
	var changed <-chan struct{}
	if follow {
		changed = r.PullChanged()
	}
	timer := r.Clock().After(d)
	for {
		select {
		case <-r.Context().Done():
			return false
		case <-timer:
			return true
		case <-changed:
			timer = r.Clock().After(r.PullInterval())
		}
	}
}

// pull makes one pull and hands each accepted job on, in pull order.
func (p *Puller) pull(inv, comp chan<- wire.Job) transport.Class {
	r := p.Run
	resp, _ := r.Call(r.Context(), transport.Request{Op: transport.OpJobs})
	if resp.Class != transport.Success {
		return resp.Class
	}
	r.SetLastPull(r.Clock().Now()) // answered 200 (#78 (b))
	var jr wire.JobsResponse
	if err := wire.DecodeStrict(resp.Body, &jr); err != nil {
		r.Log().Warn("the job pull answer failed the contract check; no job run")
		r.SetLastError("jobs answer refused")
		return transport.Drop
	}
	for _, job := range jr.Jobs {
		if !p.accept(job) {
			continue
		}
		ch := comp
		if job.Kind == "inventory" {
			ch = inv // runs at once, alongside compliance jobs (TS §3.3 L222)
		}
		select {
		case ch <- job:
		case <-r.Context().Done():
			return transport.Stop
		}
	}
	return transport.Success
}

// accept applies the TS §3.3 L212 checks and records the id as seen before
// the job is acted on, so a crash cannot run it twice. A refused id is also
// recorded, so it is never tried again.
func (p *Puller) accept(job wire.Job) bool {
	r := p.Run
	now := r.Clock().Now()
	reason := ""
	switch pickup := job.PickupBy.Time(); {
	case !strings.EqualFold(string(job.AgentID), string(r.AgentID())):
		reason = "addressed to another agent"
	case !pickup.After(now):
		reason = "pickup_by has passed"
	case pickup.After(now.Add(maxPickupAhead)):
		reason = "pickup_by is more than 25 h away"
	case p.Seen.Has(job.JobID):
		p.refuse(job, "already seen")
		return false
	}
	if err := p.Seen.Add(job.JobID); err != nil {
		r.Log().Error("the job id could not be recorded as seen; job not run", "job_id", string(job.JobID))
		r.SetLastError("seen job ids not saved")
		return false
	}
	if reason != "" {
		p.refuse(job, reason)
		return false
	}
	return true
}

func (p *Puller) refuse(job wire.Job, reason string) {
	p.Run.Log().Warn("job refused; not run", "job_id", string(job.JobID), "reason", reason)
	p.Run.SetLastError("job refused: " + reason)
}
