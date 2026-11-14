package loops

import (
	"strings"
	"sync"

	"bitscan.local/agent/internal/agent/wire"
)

// maxBatch is the most results in one batch (TS §3.3 L223).
const maxBatch = 50

// work runs the jobs of one kind one at a time, in the order they were
// accepted, until the Run stops. A job must start before its pickup_by; it
// may finish after it (TS §3.3 L212). Inventory jobs use it.
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

// pooled is one compliance job waiting or running in pool.
type pooled struct {
	job wire.Job
	ids map[wire.UUID]bool // its plugin ids, lowercased
}

func newPooled(job wire.Job) *pooled {
	ids := make(map[wire.UUID]bool, len(job.Plugins))
	for _, pl := range job.Plugins {
		ids[wire.UUID(strings.ToLower(string(pl.PluginUUID)))] = true
	}
	return &pooled{job: job, ids: ids}
}

func (e *pooled) shares(ids map[wire.UUID]bool) bool {
	for id := range e.ids {
		if ids[id] {
			return true
		}
	}
	return false
}

// pool runs compliance jobs (TS §3.3; owner decision 2026-11-14): at most
// Run.MaxParallelJobs at once, started in the order they were accepted. A
// waiting job does not start while a running job has a plugin id in common
// with it (plugin ids belong to one policy, SR BIT015: the same policy, or a
// job and its retry), and never overtakes an older waiting job it shares one
// with; a waiting job of another policy may start first. A job must start
// before its pickup_by; it may finish after it. current_job_id is the
// running job that started first. When the Run stops, pool waits for the
// running jobs (their context ends with the Run) and returns.
func (p *Puller) pool(jobs <-chan wire.Job, run func(wire.Job)) {
	r := p.Run
	var waiting, running []*pooled
	done := make(chan *pooled)
	var wg sync.WaitGroup
	defer wg.Wait()
	for {
		waiting = p.startReady(waiting, &running, done, &wg, run)
		select {
		case <-r.Context().Done():
			// Drain the finish notices so the running goroutines can end.
			go func() {
				for range done {
				}
			}()
			wg.Wait()
			close(done)
			return
		case job := <-jobs:
			waiting = append(waiting, newPooled(job))
		case e := <-done:
			for i, x := range running {
				if x == e {
					running = append(running[:i:i], running[i+1:]...)
					break
				}
			}
			p.setCurrent(running)
		case <-r.JobsChanged():
		}
	}
}

// startReady starts every waiting job that may start now, in order, and
// returns those still waiting.
func (p *Puller) startReady(waiting []*pooled, running *[]*pooled, done chan<- *pooled, wg *sync.WaitGroup, run func(wire.Job)) []*pooled {
	r := p.Run
	busy := map[wire.UUID]bool{} // plugin ids of running and older waiting jobs
	for _, e := range *running {
		for id := range e.ids {
			busy[id] = true
		}
	}
	var still []*pooled
	for _, e := range waiting {
		if !e.job.PickupBy.Time().After(r.Clock().Now()) {
			p.refuse(e.job, "pickup_by passed before the job could start")
			continue
		}
		if len(*running) >= r.MaxParallelJobs() || e.shares(busy) {
			still = append(still, e)
			for id := range e.ids {
				busy[id] = true
			}
			continue
		}
		*running = append(*running, e)
		for id := range e.ids {
			busy[id] = true
		}
		p.setCurrent(*running)
		wg.Add(1)
		go func() {
			defer wg.Done()
			run(e.job)
			done <- e
		}()
	}
	return still
}

// setCurrent reports the running job that started first, or none (#78 (c)).
func (p *Puller) setCurrent(running []*pooled) {
	if len(running) == 0 {
		p.Run.SetCurrentJob(nil)
		return
	}
	id := running[0].job.JobID
	p.Run.SetCurrentJob(&id)
}

// compliance hands one compliance job to the handler. Without a handler
// the job is refused, never run another way; inventory is not affected.
func (p *Puller) compliance(job wire.Job) {
	if p.Compliance == nil {
		p.refuse(job, "no compliance handler")
		return
	}
	p.Compliance.Handle(p.Run.Context(), job)
}
