// Package token holds the agent's one current bsa_ token for every loop and
// rotates it (TS §3.2 step 7, §6.5 Rotate; #62; plan TASK-099).
package token

import (
	"sync"

	"bitscan.local/agent/internal/agent/state"
)

// Holder is the single source of the current token. Every request reads it
// through Current, so a rotated token is used by every loop at once.
type Holder struct {
	mu  sync.RWMutex
	tok state.Token
}

// NewHolder starts with the token read from the state directory.
func NewHolder(t state.Token) *Holder {
	return &Holder{tok: t}
}

// Current returns the token and its lifetime.
func (h *Holder) Current() state.Token {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return h.tok
}

// set replaces the token; only the rotator calls it, after the new token is
// persisted.
func (h *Holder) set(t state.Token) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.tok = t
}
