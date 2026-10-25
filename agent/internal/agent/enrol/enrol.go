// Package enrol makes the start-up decision of #81 (c) and enrols the host
// with the manager (TS §3.2 steps 2–4, §6.5 Enrol). Nothing here logs; the
// caller logs the returned errors, which never hold a token.
package enrol

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/inventory"
)

const (
	// MachineIDPath and OSReleasePath are the production sources (TS §3.2
	// step 2, REQ-096).
	MachineIDPath = "/etc/machine-id"
	OSReleasePath = "/etc/os-release"
)

var (
	// ErrStop is a 401 on enrol (enrollment_rejected or any other type): the
	// loops never start and enroll.token is kept (#76, #81 (a)).
	ErrStop = errors.New("enrolment refused; the host needs a new enrolment token")
	// ErrNoCredentials is the #81 (c) start-up refusal when neither file exists.
	ErrNoCredentials = errors.New("start-up: neither token nor enroll.token exists in the state directory; the host must be enrolled")
)

// bseRe is the enrolment token shape (TS §6.2: 256 random bits, base64url,
// with its prefix). A bad file is refused before any call, so a value that
// cannot be a header is never retried.
var bseRe = regexp.MustCompile(`^bse_[A-Za-z0-9_-]{43}$`)

// Doer sends one request; *transport.Client is the production Doer.
type Doer interface {
	Do(ctx context.Context, r transport.Request) (transport.Response, error)
}

// Store is the part of *state.Store that enrolment uses.
type Store interface {
	EnrolToken() (string, error)
	Token() (state.Token, error)
	AgentID() (wire.UUID, error)
	SaveEnrolment(id wire.UUID, t state.Token) error
	DeleteEnrolToken() error
}

// Enroller holds what enrolment needs. Client, Store, MachineID and
// AgentVersion are required; a nil Clock, Backoff or Hostname, or an empty
// OSReleasePath, takes its production default.
type Enroller struct {
	Client        Doer
	Store         Store
	MachineID     wire.MachineID // from ReadMachineID
	AgentVersion  string
	Clock         schedule.Clock
	Backoff       *schedule.Backoff
	Hostname      func() (string, error)
	OSReleasePath string
}

// Result is the identity the loops run with. Status is the enrol answer's
// status, or empty when the stored token was used without enrolling. Both
// statuses start the loops; with awaiting_approval the heartbeats then wait
// on 403 pending_approval (REQ-096 (2)).
type Result struct {
	AgentID wire.UUID
	Token   state.Token
	Status  wire.EnrolStatus
}

// ReadMachineID reads path (MachineIDPath in production): exactly 32
// lowercase hex characters, optionally followed by one newline.
func ReadMachineID(path string) (wire.MachineID, error) {
	f, err := os.Open(filepath.Clean(path))
	if err != nil {
		return "", errors.New("start-up: /etc/machine-id: cannot read the file")
	}
	defer func() { _ = f.Close() }()
	b, err := io.ReadAll(io.LimitReader(f, 64))
	if err != nil {
		return "", errors.New("start-up: /etc/machine-id: cannot read the file")
	}
	id := wire.MachineID(strings.TrimSuffix(string(b), "\n"))
	if wire.Validate(id) != nil {
		return "", errors.New("start-up: /etc/machine-id: must be 32 lowercase hex characters")
	}
	return id, nil
}

// Start decides per #81 (c): when enroll.token exists the host enrols (also
// when a token exists, which is how re-enrolment works) and the answer
// replaces agent_id, token and the token times; otherwise the stored token is
// used; with neither file it returns ErrNoCredentials before any call.
func (e *Enroller) Start(ctx context.Context) (Result, error) {
	bse, err := e.Store.EnrolToken()
	switch {
	case err == nil:
		return e.enrol(ctx, bse)
	case !errors.Is(err, fs.ErrNotExist):
		return Result{}, fmt.Errorf("start-up: %w", err)
	}
	tok, err := e.Store.Token()
	if errors.Is(err, fs.ErrNotExist) {
		return Result{}, ErrNoCredentials
	}
	if err != nil {
		return Result{}, fmt.Errorf("start-up: %w", err)
	}
	id, err := e.Store.AgentID()
	if err != nil {
		return Result{}, fmt.Errorf("start-up: %w", err)
	}
	return Result{AgentID: id, Token: tok}, nil
}

// enrol calls the manager until it answers. 429, 5xx, network errors (a lost
// answer, #76) and 403 pending_approval are retried with back-off, sending
// the same token and body each time; a 401 returns ErrStop; any other answer
// is returned as an error without a retry.
func (e *Enroller) enrol(ctx context.Context, bse string) (Result, error) {
	if !bseRe.MatchString(bse) {
		return Result{}, errors.New("start-up: enroll.token: not a bse_ token")
	}
	body, err := e.body()
	if err != nil {
		return Result{}, err
	}
	clock, bo := e.Clock, e.Backoff
	if clock == nil {
		clock = schedule.RealClock{}
	}
	if bo == nil {
		bo = schedule.NewBackoff(schedule.CryptoSource{})
	}
	for {
		resp, err := e.Client.Do(ctx, transport.Request{Op: transport.OpEnrol, Token: bse, Body: body})
		switch resp.Class {
		case transport.Success:
			return e.save(resp.Body)
		case transport.Stop:
			return Result{}, ErrStop
		case transport.Retry, transport.Wait:
			if err := schedule.Sleep(ctx, clock, bo.Next()); err != nil {
				return Result{}, fmt.Errorf("enrol: %w", err)
			}
			continue
		}
		if err != nil {
			return Result{}, fmt.Errorf("enrol: %w", err)
		}
		return Result{}, fmt.Errorf("enrol: the manager refused the request with status %d", resp.Status)
	}
}

func (e *Enroller) body() ([]byte, error) {
	hostname := e.Hostname
	if hostname == nil {
		hostname = os.Hostname
	}
	host, err := hostname()
	if err != nil {
		return nil, errors.New("enrol: cannot read the host name")
	}
	path := e.OSReleasePath
	if path == "" {
		path = OSReleasePath
	}
	osID, osVersionID, osPrettyName := inventory.ReadOSRelease(path) // absent or out of bounds: null
	body, err := wire.Encode(wire.EnrolRequest{
		Hostname: host, MachineID: e.MachineID, AgentVersion: e.AgentVersion,
		OsID: osID, OsVersionID: osVersionID, OsPrettyName: osPrettyName,
	})
	if err != nil {
		return nil, fmt.Errorf("enrol: build the request: %w", err)
	}
	return body, nil
}

// save decodes the answer strictly, then writes agent_id, token and
// token.json and only then deletes enroll.token, so a crash in between
// enrols again at the next start (a re-enrolment, #76).
func (e *Enroller) save(body []byte) (Result, error) {
	var r wire.EnrolResponse
	if err := wire.DecodeStrict(body, &r); err != nil {
		return Result{}, fmt.Errorf("enrol: the manager's answer was refused: %w", err)
	}
	id := wire.UUID(strings.ToLower(string(r.AgentID)))
	tok := state.Token{Value: r.AgentToken, IssuedAt: r.IssuedAt.Time(), ExpiresAt: r.ExpiresAt.Time(), TimesKnown: true}
	if err := e.Store.SaveEnrolment(id, tok); err != nil {
		return Result{}, fmt.Errorf("enrol: %w", err)
	}
	if err := e.Store.DeleteEnrolToken(); err != nil {
		return Result{}, fmt.Errorf("enrol: %w", err)
	}
	return Result{AgentID: id, Token: tok, Status: r.Status}, nil
}
