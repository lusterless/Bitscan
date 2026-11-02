package loops

import (
	"errors"
	"os"

	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/token"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

// Heartbeat sends one heartbeat at once, then one every 300 s ± 30 s, until
// the Run stops (TS §3.3 L202). 403 pending_approval, 429, 5xx and network
// errors are retried with the back-off instead of the timer (TS §3.3 L226,
// lead ruling 2026-10-24). The answer only sets the pull interval and
// max_parallel_plugins: it never makes the agent run, fetch or upload
// anything (TS §3.3 L211). The only other call is rotation, when its window
// is open (TS §3.2 step 7).
func (r *Run) Heartbeat() {
	back := schedule.NewBackoff(r.rand)
	for r.ctx.Err() == nil {
		class := r.heartbeat()
		r.firstOnce.Do(func() { close(r.firstBeat) })
		wait := schedule.HeartbeatInterval(r.rand)
		switch class {
		case transport.Stop:
			return
		case transport.Wait, transport.Retry:
			wait = back.Next()
		default:
			back.Reset()
		}
		if schedule.Sleep(r.ctx, r.d.Clock, wait) != nil {
			return
		}
	}
}

// heartbeat makes one heartbeat call and returns its class. last_error is
// sent once and cleared; it is kept for the next heartbeat when this one was
// not answered with success, unless a newer error replaced it.
func (r *Run) heartbeat() transport.Class {
	now := r.d.Clock.Now()
	lastErr := r.lastErr.Swap(nil)
	req := wire.HeartbeatRequest{
		AgentVersion:  r.d.Version,
		UptimeS:       int64(now.Sub(r.start).Seconds()), // the agent process (#78 (a))
		CurrentJobID:  r.current.Load(),
		SpoolBytes:    r.spoolBytes(),
		LastError:     lastErr,
		RunnerHelpers: r.helpers(),
		Clock:         wire.NewTime(now),
	}
	if t := r.lastPull.Load(); t != nil {
		at := wire.NewTime(*t)
		req.LastPullAt = &at
	}
	body, err := wire.Encode(req)
	if err != nil {
		r.lastErr.CompareAndSwap(nil, lastErr)
		r.log.Error("the heartbeat body failed the contract check; not sent")
		return transport.Drop
	}
	resp, _ := r.Call(r.ctx, transport.Request{Op: transport.OpHeartbeat, Body: body})
	if resp.Class != transport.Success {
		if resp.Class != transport.Drop {
			r.lastErr.CompareAndSwap(nil, lastErr)
		}
		return resp.Class
	}
	var hr wire.HeartbeatResponse
	if err := wire.DecodeStrict(resp.Body, &hr); err != nil {
		r.log.Warn("the heartbeat answer failed the contract check; ignored")
		r.SetLastError("heartbeat answer refused")
		return transport.Drop
	}
	r.SetIntervals(hr.JobPullSeconds, hr.MaxParallelPlugins)
	if err := r.d.Rotator.MaybeRotate(r.ctx, now); errors.Is(err, token.ErrStop) {
		// A 401 on rotate is a revoked or expired token (also reuse detection,
		// which revokes both); token.ErrStop carries no type (TS §3.2 step 8).
		r.stop(true)
		return transport.Stop
	} else if err != nil && r.ctx.Err() == nil {
		r.log.Warn("token rotation failed; tried again after the next heartbeat")
	}
	return transport.Success
}

// spoolBytes is the spool's size in bytes on disk (#78 (d)).
func (r *Run) spoolBytes() int64 {
	if r.d.SpoolBytes == nil {
		return 0
	}
	return max(r.d.SpoolBytes(), 0)
}

// helpers is ["capread"] when any file exists at the capread socket path
// (#30; lead ruling 2026-10-24), else [].
func (r *Run) helpers() []wire.HelperName {
	if _, err := os.Lstat(r.d.CapreadSock); err == nil {
		return []wire.HelperName{"capread"}
	}
	return []wire.HelperName{}
}
