// Package runner is bitscan-runner: it checks and runs whole compliance jobs
// handed over on /run/bitscan/runner.sock (TS §3.5, §3.7).
package runner

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/redact"
	"bitscan.local/agent/internal/runner/proto"
)

const (
	// AgentIDPath is the agent's id file (TS §3.7 L285).
	AgentIDPath = "/var/lib/bitscan-agent/agent_id"
	// MaxSeen bounds the in-memory seen set (#132 (c)).
	MaxSeen     = 100000
	seenGrace   = time.Minute
	pickupMax   = 25 * time.Hour
	maxPlugins  = 5000
	minTimeout  = 1
	maxTimeout  = 600
	maxParallel = 8
	// An agent_id file holds a UUID and at most one LF.
	maxAgentIDFile = 64
)

var errAgentID = errors.New("runner: agent_id file unreadable")

// Checks is the runner's re-check of each request (TS §3.7 L285, #132).
// These catch mistakes, not attacks. Safe for concurrent use.
type Checks struct {
	agentIDPath string
	mu          sync.Mutex
	seen        map[wire.UUID]time.Time // job id → forget after
}

// NewChecks reads the agent id from agentIDPath for every job.
func NewChecks(agentIDPath string) *Checks {
	return &Checks{agentIDPath: agentIDPath, seen: map[wire.UUID]time.Time{}}
}

// Check runs the #132 (e) checks in their fixed order (kind, shape,
// patterns, agent_id, pickup_by, seen) on a decoded request and returns the
// refusal word, or ok. Every decoded request's job id is recorded as seen,
// refused or not, until its pickup_by + 1 min; at MaxSeen ids new jobs are
// refused seen_full until ids expire (fail closed). now is the only clock.
func (c *Checks) Check(req proto.Request, now time.Time) (proto.Reason, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	for id, until := range c.seen {
		if !now.Before(until) {
			delete(c.seen, id)
		}
	}
	reason, ok := c.check(req, now)
	id := wire.UUID(strings.ToLower(string(req.Job.JobID)))
	until := req.Job.PickupBy.Time().Add(seenGrace)
	if old, dup := c.seen[id]; dup {
		if until.After(old) {
			c.seen[id] = until
		}
		if ok {
			return proto.ReasonReplayed, false
		}
		return reason, false
	}
	if len(c.seen) >= MaxSeen {
		if ok {
			return proto.ReasonSeenFull, false
		}
		return reason, false
	}
	if now.Before(until) {
		c.seen[id] = until
	}
	return reason, ok
}

func (c *Checks) check(req proto.Request, now time.Time) (proto.Reason, bool) {
	job := req.Job
	if job.Kind != wire.KindCompliance {
		return proto.ReasonNotCompliance, false
	}
	if !pluginsOK(job.Plugins) {
		return proto.ReasonBadPlugins, false
	}
	if req.MaxParallelPlugins < 1 || req.MaxParallelPlugins > maxParallel {
		return proto.ReasonBadParallel, false
	}
	if _, err := redact.Compile(job.RedactionPatterns); err != nil {
		return proto.ReasonBadPatterns, false
	}
	own, err := readAgentID(c.agentIDPath)
	if err != nil {
		return proto.ReasonAgentIDUnreadable, false
	}
	if !strings.EqualFold(string(job.AgentID), string(own)) {
		return proto.ReasonForeignAgent, false
	}
	pickup := job.PickupBy.Time()
	if !pickup.After(now) {
		return proto.ReasonPickupPassed, false
	}
	if pickup.After(now.Add(pickupMax)) {
		return proto.ReasonPickupTooFar, false
	}
	return "", true
}

// pluginsOK: 1–5,000 plugins, plugin_uuids distinct regardless of case,
// timeout_s 1–600 (#132 (d)).
func pluginsOK(plugins []wire.PluginSpec) bool {
	if len(plugins) < 1 || len(plugins) > maxPlugins {
		return false
	}
	ids := make(map[string]bool, len(plugins))
	for _, p := range plugins {
		id := strings.ToLower(string(p.PluginUUID))
		if ids[id] || p.TimeoutS < minTimeout || p.TimeoutS > maxTimeout {
			return false
		}
		ids[id] = true
	}
	return true
}

// readAgentID reads the id file for every job (it changes at re-enrolment,
// #132 (a)). The type is checked before and after a non-blocking open, so a
// FIFO cannot hang the runner (builder checklist 14). One trailing LF is
// removed; the rest must be a UUID.
func readAgentID(path string) (wire.UUID, error) {
	p := filepath.Clean(path)
	if st, err := os.Stat(p); err != nil || !st.Mode().IsRegular() {
		return "", errAgentID
	}
	f, err := os.OpenFile(p, os.O_RDONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		return "", errAgentID
	}
	defer func() { _ = f.Close() }()
	if st, err := f.Stat(); err != nil || !st.Mode().IsRegular() {
		return "", errAgentID
	}
	b, err := io.ReadAll(io.LimitReader(f, maxAgentIDFile+1))
	if err != nil || len(b) > maxAgentIDFile {
		return "", errAgentID
	}
	id := wire.UUID(strings.TrimSuffix(string(b), "\n"))
	if wire.Validate(id) != nil {
		return "", errAgentID
	}
	return id, nil
}
