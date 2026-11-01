package loops

import (
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
// current job in the heartbeat meanwhile (#78 (c)). Without a handler the
// job is refused, never run another way; inventory is not affected.
func (p *Puller) compliance(job wire.Job) {
	if p.Compliance == nil {
		p.refuse(job, "no compliance handler")
		return
	}
	id := job.JobID
	p.Run.SetCurrentJob(&id)
	defer p.Run.SetCurrentJob(nil)
	p.Compliance.Handle(p.Run.Context(), job)
}
