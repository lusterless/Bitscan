package token

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sync"
	"time"

	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
)

// ErrStop is a 401 on rotate: every loop stops and the host must be
// re-enrolled with a new enrolment token (TS §3.2 step 8, #81).
var ErrStop = errors.New("token: the manager refused the agent token; the host must be re-enrolled with a new enrolment token")

// forbiddenWait is the pause after any Drop answer: 403 forbidden (outside
// the manager's window, by its clock) and every other answer that is not
// retried (REQ-099, plan TASK-099; user ruling 2026-10-25).
const forbiddenWait = 24 * time.Hour

// Doer sends one request; *transport.Client is the production Doer.
type Doer interface {
	Do(ctx context.Context, r transport.Request) (transport.Response, error)
}

// Saver persists a token; *state.Store is the production Saver.
type Saver interface {
	SaveToken(t state.Token) error
}

// Rotator rotates the holder's token. At most one rotate call runs at a time.
type Rotator struct {
	client    Doer
	store     Saver
	holder    *Holder
	agentID   wire.UUID
	mu        sync.Mutex // held for the whole call
	notBefore time.Time  // after 429 or 403
	stopped   bool       // after a 401: never call again until restart
}

func NewRotator(client Doer, store Saver, holder *Holder, agentID wire.UUID) *Rotator {
	return &Rotator{client: client, store: store, holder: holder, agentID: agentID}
}

// WindowStart is issued_at + max(TTL − 30 days, TTL ÷ 2), TTL being the
// token's own expires_at − issued_at (TS §3.2 L190).
func WindowStart(t state.Token) time.Time {
	ttl := t.ExpiresAt.Sub(t.IssuedAt)
	return t.IssuedAt.Add(max(ttl-30*24*time.Hour, ttl/2))
}

// MaybeRotate rotates when the window is open at now. The heartbeat loop
// calls it after each successful heartbeat; nothing else does. A call made
// while another runs returns nil at once. When the token's times are not
// known (a crash between the token and token.json writes) the window counts
// as open and the manager decides.
//
// On 200 the new token is persisted before the holder uses it; when that
// fails, or the answer is lost or unreadable, the holder keeps the old token
// and the next attempt sends it (the manager then issues a fresh token,
// decisions 2026-10-23). A 401 returns ErrStop.
func (r *Rotator) MaybeRotate(ctx context.Context, now time.Time) error {
	if !r.mu.TryLock() {
		return nil
	}
	defer r.mu.Unlock()
	if r.stopped {
		return ErrStop
	}
	cur := r.holder.Current()
	if now.Before(r.notBefore) || (cur.TimesKnown && now.Before(WindowStart(cur))) {
		return nil
	}
	body, err := wire.Encode(wire.RotateRequest{})
	if err != nil {
		return fmt.Errorf("token: encode the rotate body: %w", err)
	}
	resp, err := r.client.Do(ctx, transport.Request{
		Op: transport.OpRotate, Token: string(cur.Value), AgentID: r.agentID, Body: body,
	})
	switch resp.Class {
	case transport.Success:
		var rr wire.RotateResponse
		if err := wire.DecodeStrict(resp.Body, &rr); err != nil {
			return fmt.Errorf("token: rotate answer refused: %w", err)
		}
		next := state.Token{Value: rr.AgentToken, IssuedAt: rr.IssuedAt.Time(), ExpiresAt: rr.ExpiresAt.Time(), TimesKnown: true}
		if err := r.store.SaveToken(next); err != nil {
			return fmt.Errorf("token: persist the rotated token: %w", err)
		}
		r.holder.set(next)
		return nil
	case transport.Stop:
		r.stopped = true
		return ErrStop
	case transport.Retry:
		if resp.Status == http.StatusTooManyRequests {
			r.notBefore = now.Add(resp.RetryAfter) // the 24 h rule; tried at the next heartbeat after it
		}
		if err != nil {
			return fmt.Errorf("token: rotate: %w", err)
		}
		return fmt.Errorf("token: rotate %d %s", resp.Status, resp.Problem.Type)
	}
	if resp.Class == transport.Drop {
		r.notBefore = now.Add(forbiddenWait)
	}
	if err != nil {
		return fmt.Errorf("token: rotate: %w", err)
	}
	return fmt.Errorf("token: rotate %d %s", resp.Status, resp.Problem.Type)
}
