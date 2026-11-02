// Package proto is the agent–runner protocol on /run/bitscan/runner.sock
// (TS §3.7 L282; #29, #130). The agent sends exactly one message, a Request
// holding one whole TS §6.5 compliance Job; there is no "run this string"
// call. The runner answers accepted or refused, then one result per plugin,
// then done. Pure Go: it imports only wire and the standard library.
package proto

import (
	"errors"
	"time"
	"unicode/utf8"

	"bitscan.local/agent/internal/agent/wire"
)

const (
	Version = 1
	// MaxRequest is the agent's pull-answer cap (transport.MaxResponse).
	MaxRequest = 32 << 20
	MaxReply   = 1 << 20
	// MaxStdout and MaxStderr are UTF-8 bytes (#116 (a)).
	MaxStdout = 65536
	MaxStderr = 16384
	// minParallel and maxParallel bound max_parallel_plugins (TS §8.6).
	minParallel = 1
	maxParallel = 8
)

// Request is the only message the agent sends (#130 (c)).
type Request struct {
	V                  int      `json:"v"`
	Job                wire.Job `json:"job"`
	MaxParallelPlugins int      `json:"max_parallel_plugins"`
}

// Reason is a refusal word (#130 (d)).
type Reason string

const (
	ReasonBusy              Reason = "busy"
	ReasonMalformed         Reason = "malformed"
	ReasonNotCompliance     Reason = "not_compliance"
	ReasonBadPlugins        Reason = "bad_plugins"
	ReasonBadParallel       Reason = "bad_parallel"
	ReasonBadPatterns       Reason = "bad_patterns"
	ReasonAgentIDUnreadable Reason = "agent_id_unreadable"
	ReasonForeignAgent      Reason = "foreign_agent"
	ReasonPickupPassed      Reason = "pickup_passed"
	ReasonPickupTooFar      Reason = "pickup_too_far"
	ReasonReplayed          Reason = "replayed"
	ReasonSeenFull          Reason = "seen_full"
	ReasonInternal          Reason = "internal"
)

func (r Reason) valid() bool {
	switch r {
	case ReasonBusy, ReasonMalformed, ReasonNotCompliance, ReasonBadPlugins,
		ReasonBadParallel, ReasonBadPatterns, ReasonAgentIDUnreadable,
		ReasonForeignAgent, ReasonPickupPassed, ReasonPickupTooFar,
		ReasonReplayed, ReasonSeenFull, ReasonInternal:
		return true
	}
	return false
}

// Kind is a reply type.
type Kind string

const (
	KindAccepted Kind = "accepted"
	KindRefused  Kind = "refused"
	KindResult   Kind = "result"
	KindDone     Kind = "done"
)

// Reply is one runner message. Reason is set only for KindRefused, Result
// only for KindResult.
type Reply struct {
	Kind   Kind
	Reason Reason
	Result Result
}

var (
	// ErrFrame: a zero-length, oversize or truncated frame.
	ErrFrame = errors.New("proto: bad frame")
	// ErrMalformed: a frame whose content breaks the protocol. Errors wrapping
	// it carry fixed words only, never input text.
	ErrMalformed = errors.New("proto: malformed message")
	// ErrNotCompliance also wraps ErrMalformed; the serve loop answers it
	// not_compliance (RefusalFor).
	ErrNotCompliance = errors.New("proto: not a compliance job")
	errResult        = errors.New("proto: result item refused")
)

// RefusalFor maps a ReadRequest error to the word the runner answers. Every
// error other than an inventory job is malformed, out-of-bound values
// included (lead ruling 2026-10-30, Q1).
func RefusalFor(err error) Reason {
	if errors.Is(err, ErrNotCompliance) {
		return ReasonNotCompliance
	}
	return ReasonMalformed
}

// Result is a Results item (TS §6.5) that passed the wire bounds and the byte
// caps. Its only constructors are NewResult, ReadReply, UnavailableResult and
// OverflowMarker, so the spool and the sender can hold nothing else (REQ-247).
type Result struct{ item wire.ResultItem }

// NewResult checks item and returns it as a Result. The error carries fixed
// words only.
func NewResult(item wire.ResultItem) (Result, error) {
	item = copyItem(item)
	if err := checkItem(item); err != nil {
		return Result{}, err
	}
	return Result{item: item}, nil
}

// Item returns a copy of the item.
func (r Result) Item() wire.ResultItem { return copyItem(r.item) }

func checkItem(item wire.ResultItem) error {
	if wire.Validate(item) != nil {
		return errResult
	}
	// Go strings are bytes. Invalid UTF-8 is refused so the encoder never
	// expands a byte to U+FFFD past the cap.
	if len(item.Stdout) > MaxStdout || len(item.Stderr) > MaxStderr ||
		!utf8.ValidString(item.Stdout) || !utf8.ValidString(item.Stderr) {
		return errResult
	}
	if item.Error != nil && (item.ExitCode != nil || item.Stdout != "" || item.Stderr != "") {
		return errResult
	}
	return nil
}

func copyItem(item wire.ResultItem) wire.ResultItem {
	if item.ExitCode != nil {
		c := *item.ExitCode
		item.ExitCode = &c
	}
	if item.Error != nil {
		c := *item.Error
		item.Error = &c
	}
	return item
}

func errorItem(plugin wire.UUID, started, finished wire.Time, e wire.ResultError) Result {
	return Result{item: wire.ResultItem{
		PluginUUID: plugin,
		StartedAt:  started,
		FinishedAt: finished,
		Error:      &e,
	}}
}

// UnavailableResult is the #131 (b) item for a plugin that got no result:
// error runner_unavailable, exit_code null, empty streams, both times now.
func UnavailableResult(plugin wire.UUID, now time.Time) Result {
	t := wire.NewTime(now)
	return errorItem(plugin, t, t, wire.ErrRunnerUnavailable)
}

// OverflowMarker is the #140 marker that replaces a dropped result: it keeps
// plugin_uuid, started_at and finished_at, with error spool_overflow.
func OverflowMarker(from Result) Result {
	return errorItem(from.item.PluginUUID, from.item.StartedAt, from.item.FinishedAt, wire.ErrSpoolOverflow)
}
