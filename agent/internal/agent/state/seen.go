package state

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"strings"
	"sync"
	"time"

	"bitscan.local/agent/internal/agent/wire"
)

const (
	fileSeenJobs = "seen_jobs.json"
	// SeenFor is how long a job id is remembered (TS §3.3 L212).
	SeenFor = 7 * 24 * time.Hour
)

// Seen is the set of job ids seen in the last SeenFor, persisted in
// seen_jobs.json as {"<job_id>": "<first seen, RFC 3339>"}. It is safe for
// concurrent use.
type Seen struct {
	store *Store
	now   func() time.Time
	mu    sync.Mutex
	ids   map[wire.UUID]time.Time
}

// LoadSeen reads seen_jobs.json, using now as its only clock. A missing file
// is an empty set; a corrupt or unreadable one is an error, and the agent
// refuses to start (fail closed: starting empty would allow a replay; lead
// ruling 2026-10-24).
func (s *Store) LoadSeen(now func() time.Time) (*Seen, error) {
	j := &Seen{store: s, now: now, ids: map[wire.UUID]time.Time{}}
	b, err := s.root.ReadFile(fileSeenJobs)
	if errors.Is(err, fs.ErrNotExist) {
		return j, nil
	}
	if err != nil {
		return nil, fmt.Errorf("state: read seen_jobs.json: %w", err)
	}
	var raw map[string]time.Time
	if err := json.Unmarshal(b, &raw); err != nil || raw == nil {
		return nil, errors.New("state: seen_jobs.json: unreadable")
	}
	for k, t := range raw {
		id := wire.UUID(strings.ToLower(k))
		if wire.Validate(id) != nil {
			return nil, errors.New("state: seen_jobs.json: unreadable")
		}
		j.ids[id] = t
	}
	j.prune()
	return j, nil
}

// Has reports whether id was seen less than SeenFor ago.
func (j *Seen) Has(id wire.UUID) bool {
	j.mu.Lock()
	defer j.mu.Unlock()
	t, ok := j.ids[wire.UUID(strings.ToLower(string(id)))]
	return ok && j.now().Sub(t) < SeenFor
}

// Add records id as seen now and persists the set before it returns, so a
// job is recorded before it is acted on. An id already present keeps its
// first-seen time.
func (j *Seen) Add(id wire.UUID) error {
	id = wire.UUID(strings.ToLower(string(id)))
	if err := wire.Validate(id); err != nil {
		return errors.New("state: job id: not a UUID")
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	j.prune()
	if _, ok := j.ids[id]; !ok {
		j.ids[id] = j.now().UTC()
	}
	b, err := json.Marshal(j.ids)
	if err != nil {
		return fmt.Errorf("state: encode seen_jobs.json: %w", err)
	}
	return j.store.writeFile(fileSeenJobs, b, 0o600)
}

// prune forgets ids seen SeenFor or longer ago. Callers hold j.mu (or own j).
func (j *Seen) prune() {
	now := j.now()
	for id, t := range j.ids {
		if now.Sub(t) >= SeenFor {
			delete(j.ids, id)
		}
	}
}
