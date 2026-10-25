// Package schedule holds the agent's timing: the jittered loop intervals
// (TS §3.3) and the retry back-off, on an injected clock and an injected
// random source so tests run on a fake clock with seeded randomness.
package schedule

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"time"
)

const (
	// Heartbeat is the fixed heartbeat period (TS §3.3, #4).
	Heartbeat = 300 * time.Second
	// Jitter is the ± spread on both loop intervals (TS §3.3).
	Jitter = 30 * time.Second
	// PullMin and PullMax clamp job_pull_seconds (TS §3.3 L203, L206).
	PullMin = 60
	PullMax = 3600
)

// Clock is the only time source the agent's loops use.
type Clock interface {
	Now() time.Time
	After(d time.Duration) <-chan time.Time
}

// RealClock is the wall clock.
type RealClock struct{}

func (RealClock) Now() time.Time                         { return time.Now() }
func (RealClock) After(d time.Duration) <-chan time.Time { return time.After(d) }

// Sleep waits d on c, or returns ctx's error as soon as ctx is done.
func Sleep(ctx context.Context, c Clock, d time.Duration) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-c.After(d):
		return nil
	}
}

// Source gives uniform values in [0, 1).
type Source interface{ Float64() float64 }

// CryptoSource draws from crypto/rand. Jitter needs no secrecy; crypto/rand
// simply avoids a seeded global generator in production.
type CryptoSource struct{}

func (CryptoSource) Float64() float64 {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		return 0.5 // crypto/rand does not fail on Linux; the midpoint keeps the bound
	}
	return float64(binary.BigEndian.Uint64(b[:])>>11) / (1 << 53)
}

// HeartbeatInterval is 300 s ± 30 s, uniform.
func HeartbeatInterval(src Source) time.Duration {
	return jittered(Heartbeat, src)
}

// ClampPull clamps a job_pull_seconds value to 60–3,600.
func ClampPull(seconds int) int {
	return min(max(seconds, PullMin), PullMax)
}

// PullInterval is ClampPull(seconds) ± 30 s, uniform.
func PullInterval(seconds int, src Source) time.Duration {
	return jittered(time.Duration(ClampPull(seconds))*time.Second, src)
}

func jittered(base time.Duration, src Source) time.Duration {
	return base - Jitter + time.Duration(src.Float64()*float64(2*Jitter))
}
