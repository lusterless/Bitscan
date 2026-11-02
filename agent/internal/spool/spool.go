// Package spool keeps finished, already-redacted results on disk until the
// manager has answered them (TS §3.3 L226; #139). Under the spool directory
// each job has <job_id>/job.json (its Manifest) and one <seq>.json per
// pending Results item. Every write is atomic and all access goes through
// os.Root, so no path or symlink leads outside the directory. Size is the
// sum of the files' bytes, bounded by maxBytes (spool_max_mb MiB, #57).
package spool

import (
	"cmp"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"path"
	"slices"
	"strings"
	"sync"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

var (
	ErrFull          = errors.New("spool: full")
	ErrUnknownJob    = errors.New("spool: no such job")
	ErrJobEnded      = errors.New("spool: job already finished or interrupted")
	ErrUnknownPlugin = errors.New("spool: plugin not in the job")
	errNotInFlight   = errors.New("spool: batch not handed out")
)

// bodyOverhead is len(`{"results":[],"final":false}`), the ResultsRequest
// body around its items; items are joined by one comma each.
const bodyOverhead = 28

type entry struct {
	seq    uint64
	size   int64
	putAt  time.Time // zero after Open: such a job is never running
	full   bool      // a full result, not an error item (overflow, #140)
	flight bool      // in a batch handed out by Next
}

func newEntry(seq uint64, size int64, r proto.Result, putAt time.Time) *entry {
	return &entry{seq: seq, size: size, putAt: putAt, full: r.Item().Error == nil}
}

type job struct {
	m       Manifest
	mSize   int64
	items   []*entry // by seq
	nextSeq uint64
	flight  bool
}

func (j *job) running() bool   { return !j.m.Finished && !j.m.Interrupted }
func (j *job) removable() bool { return len(j.items) == 0 && (j.m.FinalAcked || j.m.Interrupted) }

// Spool is safe for concurrent use.
type Spool struct {
	// Log is used by overflow handling (TASK-219); nil means slog.Default().
	Log   *slog.Logger
	root  *os.Root
	max   int64
	now   func() time.Time
	mu    sync.Mutex
	size  int64
	jobs  []*job // by ReceivedAt, then JobID (#139 (c))
	crash func(file, step string) error
}

// Batch is one post: the start notice, items, or the final batch.
type Batch struct {
	Job   wire.UUID
	Start bool
	Items []proto.Result
	Final bool
	seqs  []uint64
}

// Open opens (creating it 0700 if needed) the spool directory. It deletes
// leftover temporary files, drops unreadable entries and jobs received more
// than 7 days ago, and marks every job that had not finished interrupted:
// its items are still sent, its final batch never (#131 (d)).
func Open(dir string, maxBytes int64, now func() time.Time) (*Spool, []Dropped, error) {
	if err := os.Mkdir(dir, 0o700); err != nil && !errors.Is(err, fs.ErrExist) {
		return nil, nil, fmt.Errorf("spool: create the directory: %w", err)
	}
	if fi, err := os.Lstat(dir); err != nil || !fi.IsDir() {
		return nil, nil, errors.New("spool: the spool path is not a directory")
	}
	root, err := os.OpenRoot(dir)
	if err != nil {
		return nil, nil, fmt.Errorf("spool: open the directory: %w", err)
	}
	s := &Spool{root: root, max: maxBytes, now: now}
	dropped, err := s.load()
	if err != nil {
		_ = root.Close()
		return nil, nil, err
	}
	return s, dropped, nil
}

func (s *Spool) load() ([]Dropped, error) {
	ents, err := fs.ReadDir(s.root.FS(), ".")
	if err != nil {
		return nil, fmt.Errorf("spool: list the directory: %w", err)
	}
	var dropped []Dropped
	for _, e := range ents {
		id := wire.UUID(e.Name())
		if !e.Type().IsDir() || wire.Validate(id) != nil || e.Name() != strings.ToLower(e.Name()) {
			continue
		}
		j, bad, err := s.loadJob(id)
		d := Dropped{Job: id, Reason: "unreadable"}
		if err == nil {
			dropped = append(dropped, bad...)
			if s.now().Sub(j.m.ReceivedAt.Time()) <= keepFor {
				s.size += j.mSize
				for _, e := range j.items {
					s.size += e.size
				}
				s.add(j)
				if err := s.reopen(j); err != nil {
					return nil, err
				}
				continue
			}
			d.Items, d.Reason = len(j.items), "expired"
		}
		if err := s.root.RemoveAll(string(id)); err != nil {
			return nil, fmt.Errorf("spool: remove a dropped job: %w", err)
		}
		dropped = append(dropped, d)
	}
	return dropped, s.syncDir(".")
}

// add indexes a job whose files are already counted in s.size.
func (s *Spool) add(j *job) {
	s.jobs = append(s.jobs, j)
	slices.SortFunc(s.jobs, func(a, b *job) int {
		return cmp.Or(a.m.ReceivedAt.Time().Compare(b.m.ReceivedAt.Time()), cmp.Compare(a.m.JobID, b.m.JobID))
	})
}

func (s *Spool) reopen(j *job) error {
	if j.running() {
		j.m.Interrupted = true
		if !j.removable() {
			return s.saveManifest(j)
		}
	}
	if j.removable() {
		return s.removeJob(j)
	}
	return nil
}

func (s *Spool) find(id wire.UUID) *job {
	id = wire.UUID(strings.ToLower(string(id)))
	for _, j := range s.jobs {
		if j.m.JobID == id {
			return j
		}
	}
	return nil
}

// StartJob records a job before the runner is contacted; its start notice
// is then pending. plugins are the job's uuids in payload order.
func (s *Spool) StartJob(id wire.UUID, plugins []wire.UUID) error {
	id = wire.UUID(strings.ToLower(string(id)))
	m := Manifest{JobID: id, ReceivedAt: wire.NewTime(s.now().UTC()), Plugins: make([]wire.UUID, len(plugins))}
	for i, p := range plugins {
		m.Plugins[i] = wire.UUID(strings.ToLower(string(p)))
	}
	b, err := wire.Encode(m)
	if err != nil {
		return fmt.Errorf("spool: job: %w", err)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.find(id) != nil {
		return errors.New("spool: job already spooled")
	}
	if s.size+int64(len(b)) > s.max {
		return ErrFull
	}
	if err := s.root.Mkdir(string(id), 0o700); err != nil {
		return fmt.Errorf("spool: create a job directory: %w", err)
	}
	j := &job{m: m, nextSeq: 1}
	if err := s.saveManifest(j); err != nil { // counts the manifest only on success
		_ = s.root.RemoveAll(string(id))
		return err
	}
	s.add(j)
	return s.syncDir(".")
}

// Put spools one result of a running job.
func (s *Spool) Put(id wire.UUID, r proto.Result) error {
	item := r.Item()
	b, err := wire.Encode(item)
	if err != nil {
		return fmt.Errorf("spool: item: %w", err)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	j := s.find(id)
	switch {
	case j == nil:
		return ErrUnknownJob
	case !j.running():
		return ErrJobEnded
	case !slices.Contains(j.m.Plugins, wire.UUID(strings.ToLower(string(item.PluginUUID)))):
		return ErrUnknownPlugin
	}
	if r, b, err = s.fit(j, r, b); err != nil { // overflow.go (#140)
		return err
	}
	n, err := s.writeFile(path.Join(string(j.m.JobID), itemName(j.nextSeq)), b)
	if err != nil {
		return err
	}
	j.items = append(j.items, newEntry(j.nextSeq, n, r, s.now()))
	j.nextSeq++
	s.size += n
	return nil
}

// Finish marks a job finished: its final batch follows its items. It is not
// called when the agent stops mid-job.
func (s *Spool) Finish(id wire.UUID) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	j := s.find(id)
	if j == nil {
		return ErrUnknownJob
	}
	if !j.running() {
		return ErrJobEnded
	}
	j.m.Finished = true
	return s.saveManifest(j)
}

// Size is the spool's size in bytes on disk (heartbeat spool_bytes, #78 (d)).
func (s *Spool) Size() int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.size
}

// Next hands out the oldest postable batch: a job's start notice first, then
// up to maxItems items whose body stays within maxBytes, then (finished jobs
// only) the final batch, which is the last items batch when that empties the
// job. A running job's batch that is not full is held until its oldest item
// is holdYoung old (#141). A job has at most one batch out until Ack or Drop.
func (s *Spool) Next(maxItems, maxBytes int, holdYoung time.Duration) (Batch, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, j := range s.jobs {
		if b, ok := s.batch(j, maxItems, int64(maxBytes), holdYoung); ok {
			j.flight = true
			for _, e := range j.items[:len(b.seqs)] {
				e.flight = true
			}
			return b, true
		}
	}
	return Batch{}, false
}

func (s *Spool) batch(j *job, maxItems int, maxBytes int64, holdYoung time.Duration) (Batch, bool) {
	b := Batch{Job: j.m.JobID}
	switch {
	case j.flight:
		return b, false
	case !j.m.StartAcked:
		b.Start = true
		return b, true
	case len(j.items) == 0:
		b.Final = j.m.Finished && !j.m.FinalAcked
		return b, b.Final
	}
	total := int64(bodyOverhead - 1)
	for i, e := range j.items {
		if len(b.Items) == maxItems || (len(b.Items) > 0 && total+e.size+1 > maxBytes) {
			break
		}
		r, err := s.readItem(path.Join(string(j.m.JobID), itemName(e.seq)))
		if err != nil { // never send what does not check; drop it and retry
			if s.removeItems(j, []uint64{e.seq}) != nil || i > 0 {
				return b, false
			}
			return s.batch(j, maxItems, maxBytes, holdYoung)
		}
		b.Items, b.seqs, total = append(b.Items, r), append(b.seqs, e.seq), total+e.size+1
	}
	all := len(b.seqs) == len(j.items)
	if j.running() && all && len(b.Items) < maxItems && s.now().Sub(j.items[0].putAt) < holdYoung {
		return b, false
	}
	b.Final = j.m.Finished && all
	return b, true
}

// Ack settles a batch the manager accepted.
func (s *Spool) Ack(b Batch) error { return s.settle(b) }

// Drop settles a batch the manager will never accept (TS §3.3 L224): only
// that batch is dropped; later batches of the job are still tried (#139 (e)).
func (s *Spool) Drop(b Batch) error { return s.settle(b) }

// Release hands a batch back unanswered (a failed post attempt): its items
// stay spooled and may be converted by overflow again; nothing is removed
// and the start and final states are unchanged. Next builds a fresh batch.
func (s *Spool) Release(b Batch) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	j := s.find(b.Job)
	if j == nil || !j.flight {
		return errNotInFlight
	}
	j.flight = false
	for _, e := range j.items {
		e.flight = false
	}
	return nil
}

func (s *Spool) settle(b Batch) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	j := s.find(b.Job)
	if j == nil || !j.flight {
		return errNotInFlight
	}
	j.flight = false
	for _, e := range j.items {
		e.flight = false
	}
	if err := s.removeItems(j, b.seqs); err != nil {
		return err
	}
	changed := !j.m.StartAcked || (b.Final && !j.m.FinalAcked)
	j.m.StartAcked = true // a drop of the notice also ends it (plan TASK-212 §3)
	j.m.FinalAcked = j.m.FinalAcked || b.Final
	if j.removable() {
		return s.removeJob(j)
	}
	if changed {
		return s.saveManifest(j)
	}
	return nil
}

func (s *Spool) removeItems(j *job, seqs []uint64) error {
	for _, seq := range seqs {
		i := slices.IndexFunc(j.items, func(e *entry) bool { return e.seq == seq })
		if i < 0 {
			continue
		}
		err := s.root.Remove(path.Join(string(j.m.JobID), itemName(seq)))
		if err != nil && !errors.Is(err, fs.ErrNotExist) {
			return fmt.Errorf("spool: remove an item: %w", err)
		}
		s.size -= j.items[i].size
		j.items = slices.Delete(j.items, i, i+1)
	}
	if len(seqs) == 0 {
		return nil
	}
	return s.syncDir(string(j.m.JobID))
}

func (s *Spool) removeJob(j *job) error {
	if err := s.root.RemoveAll(string(j.m.JobID)); err != nil {
		return fmt.Errorf("spool: remove a job directory: %w", err)
	}
	s.size -= j.mSize
	for _, e := range j.items {
		s.size -= e.size
	}
	s.jobs = slices.DeleteFunc(s.jobs, func(x *job) bool { return x == j })
	return s.syncDir(".")
}

// Close closes the spool directory.
func (s *Spool) Close() error { return s.root.Close() }
