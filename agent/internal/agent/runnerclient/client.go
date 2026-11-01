// Package runnerclient hands one whole compliance job to bitscan-runner on
// /run/bitscan/runner.sock and reads its replies (TS §3.5 L249, §3.7 L282;
// #130, #131). It is the agent's only runner call: there is no other request,
// and it never logs or keeps a reply body.
package runnerclient

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"strings"
	"sync"
	"time"

	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

// Socket is the runner's socket, created by bitscan-runner.socket (TS §3.7).
const Socket = "/run/bitscan/runner.sock"

const (
	firstReply = 30 * time.Second // connect → first reply (#130 (f))
	slack      = 30 * time.Second // max(timeout_s) + slack between replies
	busyRetry  = 2 * time.Second  // #130 (g)
	busyFor    = 30 * time.Second
)

// Failure means the runner is unavailable for this job (#131 (a)). Word is
// connect, timeout, broken, protocol or refused_<reason> (#131 (c)).
type Failure struct{ Word string }

func (f *Failure) Error() string { return "runnerclient: runner unavailable: " + f.Word }

// Client talks to the runner. Zero fields take their defaults.
type Client struct {
	Socket string
	Dial   func(ctx context.Context, path string) (net.Conn, error)
	Clock  schedule.Clock
}

func (c *Client) clock() schedule.Clock {
	if c.Clock == nil {
		return schedule.RealClock{}
	}
	return c.Clock
}

// Run sends one request holding job and maxParallel, and calls onResult for
// each result in the order received. It returns nil after "done", a *Failure
// for every #131 (a) case, ctx.Err() when the agent is stopping (#131 (d)),
// or onResult's error (wrapped) after closing the connection.
func (c *Client) Run(ctx context.Context, job wire.Job, maxParallel int, onResult func(proto.Result) error) error {
	first := c.clock().Now()
	for {
		err := c.once(ctx, job, maxParallel, onResult)
		var f *Failure
		if !errors.As(err, &f) || f.Word != "refused_"+string(proto.ReasonBusy) {
			return err
		}
		if c.clock().Now().Sub(first)+busyRetry > busyFor {
			return err
		}
		if err := schedule.Sleep(ctx, c.clock(), busyRetry); err != nil {
			return err // ctx.Err(): the agent is stopping
		}
	}
}

// arm calls interrupt once d passes on the clock, or when ctx ends. The
// returned stop reports whether the clock fired.
func (c *Client) arm(ctx context.Context, d time.Duration, interrupt func()) (stop func() bool) {
	done, exited := make(chan struct{}), make(chan struct{})
	var fired bool
	go func() {
		defer close(exited)
		select {
		case <-c.clock().After(d):
			fired = true
			interrupt()
		case <-ctx.Done():
			interrupt()
		case <-done:
		}
	}()
	var once sync.Once
	return func() bool {
		once.Do(func() { close(done) })
		<-exited
		return fired
	}
}

func (c *Client) once(ctx context.Context, job wire.Job, maxParallel int, onResult func(proto.Result) error) error {
	dctx, cancel := context.WithCancel(ctx)
	stop := c.arm(ctx, firstReply, cancel)
	conn, err := c.dial(dctx)
	if err != nil {
		stop()
		cancel()
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return &Failure{Word: "connect"}
	}
	defer func() { _ = conn.Close() }()
	stop()
	cancel()
	interrupt := func() { _ = conn.SetDeadline(time.Unix(1, 0)) }

	// The first reply is due 30 s after connecting, the request write included.
	stop = c.arm(ctx, firstReply, interrupt)
	werr := proto.WriteRequest(conn, proto.Request{V: proto.Version, Job: job, MaxParallelPlugins: maxParallel})
	if errors.Is(werr, proto.ErrMalformed) || errors.Is(werr, proto.ErrFrame) {
		stop()
		return &Failure{Word: "protocol"} // not sendable; nothing was written
	}
	// After a failed write a refusal may still be readable (busy is sent
	// before the request is read), so the reply decides.
	rep, err := proto.ReadReply(conn)
	if f := c.classify(ctx, stop(), err); f != nil {
		return f
	}
	switch {
	case rep.Kind == proto.KindRefused:
		return &Failure{Word: "refused_" + string(rep.Reason)}
	case werr != nil:
		return &Failure{Word: "broken"}
	case rep.Kind != proto.KindAccepted:
		return &Failure{Word: "protocol"}
	}

	gap, want := slack, map[wire.UUID]bool{}
	for _, p := range job.Plugins {
		want[lower(p.PluginUUID)] = true
		gap = max(gap, time.Duration(p.TimeoutS)*time.Second+slack)
	}
	for {
		stop = c.arm(ctx, gap, interrupt)
		rep, err := proto.ReadReply(conn)
		if f := c.classify(ctx, stop(), err); f != nil {
			return f
		}
		switch rep.Kind {
		case proto.KindDone:
			if len(want) > 0 { // done before every plugin's result
				return &Failure{Word: "protocol"}
			}
			return nil
		case proto.KindResult:
			id := lower(rep.Result.Item().PluginUUID)
			if !want[id] { // not in the job, or already received
				return &Failure{Word: "protocol"}
			}
			delete(want, id)
			if err := onResult(rep.Result); err != nil {
				return fmt.Errorf("runnerclient: result not kept: %w", err)
			}
		default:
			return &Failure{Word: "protocol"}
		}
	}
}

// classify maps a read error to its #131 (c) word; ctx's end wins.
func (c *Client) classify(ctx context.Context, fired bool, err error) error {
	switch {
	case err == nil:
		return nil
	case ctx.Err() != nil:
		return ctx.Err()
	case fired:
		return &Failure{Word: "timeout"}
	case errors.Is(err, io.ErrUnexpectedEOF): // the connection ended inside a frame
		return &Failure{Word: "broken"}
	case errors.Is(err, proto.ErrFrame), errors.Is(err, proto.ErrMalformed):
		return &Failure{Word: "protocol"}
	}
	return &Failure{Word: "broken"} // EOF before done, or a connection error
}

func (c *Client) dial(ctx context.Context) (net.Conn, error) {
	path := c.Socket
	if path == "" {
		path = Socket
	}
	if c.Dial != nil {
		return c.Dial(ctx, path)
	}
	var d net.Dialer
	return d.DialContext(ctx, "unix", path)
}

func lower(u wire.UUID) wire.UUID { return wire.UUID(strings.ToLower(string(u))) }
