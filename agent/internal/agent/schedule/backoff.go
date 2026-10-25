package schedule

import "time"

const (
	// BackoffFirst and BackoffCap are the TS §3.3 L226 bounds: 10 s doubling
	// to a 5-minute cap.
	BackoffFirst = 10 * time.Second
	BackoffCap   = 5 * time.Minute
	// backoffSpread is the jitter on each nominal step: ±10 %, so a delay is
	// never above 330 s (lead ruling 2026-10-24).
	backoffSpread = 0.1
)

// Backoff gives the retry delays for one loop: nominal 10, 20, 40, 80, 160,
// then 300 s for every further failure, each within ±10 %. Reset after a
// success starts again at 10 s. A Backoff belongs to one goroutine.
type Backoff struct {
	src     Source
	nominal time.Duration
}

func NewBackoff(src Source) *Backoff {
	return &Backoff{src: src}
}

// Next returns the delay before the next retry and advances the step.
func (b *Backoff) Next() time.Duration {
	if b.nominal == 0 {
		b.nominal = BackoffFirst
	} else {
		b.nominal = min(2*b.nominal, BackoffCap)
	}
	factor := 1 - backoffSpread + 2*backoffSpread*b.src.Float64()
	return time.Duration(float64(b.nominal) * factor)
}

// Reset is called after a success.
func (b *Backoff) Reset() { b.nominal = 0 }
