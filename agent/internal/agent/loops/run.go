// Package loops runs the agent's two independent timers, heartbeat and job
// pull (TS §3.3), and the inventory uploads. run.go is the state they share;
// each loop lives in its own file and talks to the others only through Run.
package loops

import (
	"context"
	"errors"
	"log/slog"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/token"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

// CapreadSock is the helper socket whose presence means the capread helper
// is enabled (#30; TS §3.7 L484). The agent never connects to it.
const CapreadSock = "/run/bitscan/capread.sock"

// maxLastError is HeartbeatRequest.last_error's bound (#78 (e)).
const maxLastError = 1024

// ErrStopped is Call's error once a 401 has stopped the loops.
var ErrStopped = errors.New("loops: stopped after a 401; the host must be re-enrolled")

// Doer sends one request; *transport.Client is the production Doer.
type Doer interface {
	Do(ctx context.Context, r transport.Request) (transport.Response, error)
}

// Rotator is called after each successful heartbeat; *token.Rotator.
type Rotator interface {
	MaybeRotate(ctx context.Context, now time.Time) error
}

// InventoryRunner collects and uploads inventory (TASK-104). RunJob is called
// at once for each accepted inventory job, Unscheduled for each watcher
// signal. Both return when the upload is done, dropped, given up or ctx ends.
type InventoryRunner interface {
	RunJob(ctx context.Context, jobID wire.UUID)
	Unscheduled(ctx context.Context)
}

// ComplianceHandler handles one accepted compliance job (TASK-103, #74).
type ComplianceHandler interface {
	Handle(ctx context.Context, job wire.Job)
}

// Deps is what NewRun needs. JobPullSeconds and MaxParallelPlugins are the
// agent.yaml values, used until a heartbeat answer replaces them (TS §3.3).
type Deps struct {
	Client             Doer
	Tokens             *token.Holder
	Rotator            Rotator
	AgentID            wire.UUID
	Version            string
	Clock              schedule.Clock
	Rand               schedule.Source
	Log                *slog.Logger
	JobPullSeconds     int
	MaxParallelPlugins int
	CapreadSock        string // empty: CapreadSock
}

// Run is the state the loops share. Its context ends on a 401 (Stop) or when
// the parent ends (SIGTERM); a stopped Run stays idle, the process stays up
// until it is restarted (#81 (a)).
type Run struct {
	ctx         context.Context
	cancel      context.CancelFunc
	d           Deps
	rand        *lockedSource
	log         *slog.Logger
	start       time.Time
	stopOnce    sync.Once
	stopped     atomic.Bool
	pullSec     atomic.Int64
	maxParallel atomic.Int64
	lastErr     atomic.Pointer[string]
	lastPull    atomic.Pointer[time.Time]
	current     atomic.Pointer[wire.UUID]
	pullChanged chan struct{}
	firstBeat   chan struct{}
	firstOnce   sync.Once
}

// NewRun builds the shared state under parent.
func NewRun(parent context.Context, d Deps) *Run {
	if d.CapreadSock == "" {
		d.CapreadSock = CapreadSock
	}
	log := d.Log
	if log == nil {
		log = slog.Default()
	}
	ctx, cancel := context.WithCancel(parent)
	r := &Run{
		ctx: ctx, cancel: cancel, d: d,
		rand:        &lockedSource{src: d.Rand},
		log:         log.With("agent_id", string(d.AgentID)),
		start:       d.Clock.Now(),
		pullChanged: make(chan struct{}, 1),
		firstBeat:   make(chan struct{}),
	}
	r.SetIntervals(d.JobPullSeconds, d.MaxParallelPlugins)
	<-r.pullChanged // the initial value is not a change
	return r
}

func (r *Run) Context() context.Context { return r.ctx }
func (r *Run) Clock() schedule.Clock    { return r.d.Clock }
func (r *Run) Rand() schedule.Source    { return r.rand }
func (r *Run) Log() *slog.Logger        { return r.log }
func (r *Run) AgentID() wire.UUID       { return r.d.AgentID }

// Stopped reports whether a 401 stopped the loops.
func (r *Run) Stopped() bool { return r.stopped.Load() }

// Stop stops every loop after a 401 and logs the re-enrol line once (TS §3.2
// step 8, #81). problemType picks the line; "" when it is not known.
// token_revoked, token_expired (TS §3.2 step 8) and enrollment_rejected
// (REQ-096 (3)) say a new enrolment token is needed.
func (r *Run) Stop(problemType string) {
	r.stop(problemType == "token_revoked" || problemType == "token_expired" || problemType == "enrollment_rejected")
}

func (r *Run) stop(newEnrolment bool) {
	r.stopOnce.Do(func() {
		r.stopped.Store(true)
		r.cancel()
		if newEnrolment {
			r.log.Error("the manager refused the agent token; all loops stopped; the host must be re-enrolled with a new enrolment token")
			return
		}
		r.log.Error("the manager refused the agent; all loops stopped; the host must be re-enrolled")
	})
}

// Call sends req with the current token. A Stop answer stops every loop; a
// Drop answer is logged and kept as last_error. The caller handles Wait and
// Retry with its own back-off.
func (r *Run) Call(ctx context.Context, req transport.Request) (transport.Response, error) {
	if r.stopped.Load() {
		return transport.Response{Class: transport.Stop}, ErrStopped
	}
	req.Token = string(r.d.Tokens.Current().Value)
	req.AgentID = r.d.AgentID
	resp, err := r.d.Client.Do(ctx, req)
	switch resp.Class {
	case transport.Retry:
		if transport.IsVerifyError(err) {
			r.log.Error("the manager's certificate or key pin failed verification; nothing was sent; retried with back-off", "route", req.Op.String())
		}
	case transport.Stop:
		r.Stop(resp.Problem.Type)
	case transport.Drop:
		text := req.Op.String() + " not sent"
		if resp.Status != 0 {
			text = req.Op.String() + " " + strconv.Itoa(resp.Status) + " " + printable(resp.Problem.Type)
		}
		r.log.Warn("the manager will not accept this request; it is not retried", "last_error", text)
		r.SetLastError(text)
	}
	return resp, err
}

// SetLastError keeps text (a fixed reason) for the next heartbeat (#78 (e)).
func (r *Run) SetLastError(text string) {
	if n := []rune(text); len(n) > maxLastError {
		text = string(n[:maxLastError])
	}
	r.lastErr.Store(&text)
}

// SetIntervals applies the manager's values, clamped (TS §3.3 L206). A new
// pull interval wakes the pull loop so it reschedules.
func (r *Run) SetIntervals(pullSeconds, maxParallel int) {
	r.maxParallel.Store(int64(min(max(maxParallel, 1), 8)))
	next := int64(schedule.ClampPull(pullSeconds))
	if old := r.pullSec.Swap(next); old != next {
		select {
		case r.pullChanged <- struct{}{}:
		default:
		}
	}
}

// PullInterval is the current job_pull_seconds ± 30 s.
func (r *Run) PullInterval() time.Duration {
	return schedule.PullInterval(int(r.pullSec.Load()), r.rand)
}

// PullChanged receives a value when the pull interval changed.
func (r *Run) PullChanged() <-chan struct{} { return r.pullChanged }

func (r *Run) MaxParallelPlugins() int { return int(r.maxParallel.Load()) }

// FirstHeartbeat is closed once the first heartbeat was attempted; the first
// pull waits for it (plan TASK-101).
func (r *Run) FirstHeartbeat() <-chan struct{} { return r.firstBeat }

// SetLastPull records a pull answered 200 (#78 (b)).
func (r *Run) SetLastPull(t time.Time) { r.lastPull.Store(&t) }

// SetCurrentJob sets the compliance job being handled, or nil (#78 (c)).
func (r *Run) SetCurrentJob(id *wire.UUID) { r.current.Store(id) }

// printable keeps a manager-sent problem type to visible ASCII, so last_error
// always passes the contract and a log line stays one line.
func printable(s string) string {
	return strings.Map(func(c rune) rune {
		if c < 0x21 || c > 0x7e {
			return '?'
		}
		return c
	}, s)
}

// lockedSource lets the loops share one random source.
type lockedSource struct {
	mu  sync.Mutex
	src schedule.Source
}

func (l *lockedSource) Float64() float64 {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.src.Float64()
}
