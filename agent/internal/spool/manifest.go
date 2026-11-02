package spool

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path"
	"runtime"
	"strconv"
	"strings"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

const (
	manifestName = "job.json"
	itemSuffix   = ".json"
	tmpSuffix    = ".tmp"
	// keepFor: the manager refuses results after dispatched_at + 7 days
	// (TS §4.4 L578), so older entries are dropped at Open (#139 (g)).
	keepFor = 7 * 24 * time.Hour
)

// Manifest is a job's spool record (#139 (a)). It holds plugin uuids only:
// never a command, pattern or evaluation data (TS §3.5 L248).
type Manifest struct {
	JobID       wire.UUID   `json:"job_id"`
	ReceivedAt  wire.Time   `json:"received_at"`
	Plugins     []wire.UUID `json:"plugins" wire:"min=1,max=5000"`
	StartAcked  bool        `json:"start_acked"`
	Finished    bool        `json:"finished"`
	Interrupted bool        `json:"interrupted"`
	FinalAcked  bool        `json:"final_acked"`
}

// Dropped is a job (or some of its items) removed at Open. Reason is
// "expired" (received more than 7 days ago) or "unreadable".
type Dropped struct {
	Job    wire.UUID
	Items  int
	Reason string
}

func itemName(seq uint64) string { return fmt.Sprintf("%012d%s", seq, itemSuffix) }

func (s *Spool) step(file, step string) error {
	if s.crash == nil {
		return nil
	}
	return s.crash(file, step)
}

// writeFile replaces name (a path inside the root) atomically: a .tmp file
// created O_EXCL at 0600, written, fsynced, renamed, then the directory
// fsynced. It returns the new file's size. A crash leaves at most a .tmp,
// which Open deletes unread (REQ-247 (2)).
func (s *Spool) writeFile(name string, data []byte) (int64, error) {
	tmp := name + tmpSuffix
	if err := s.root.Remove(tmp); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return 0, fmt.Errorf("spool: remove a stale temporary file: %w", err)
	}
	f, err := s.root.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return 0, fmt.Errorf("spool: create a temporary file: %w", err)
	}
	werr := func() error {
		if err := f.Chmod(0o600); err != nil {
			return fmt.Errorf("spool: chmod: %w", err)
		}
		if err := s.step(name, "created"); err != nil {
			return err
		}
		if _, err := f.Write(data); err != nil {
			return fmt.Errorf("spool: write: %w", err)
		}
		if err := s.step(name, "written"); err != nil {
			return err
		}
		if err := f.Sync(); err != nil {
			return fmt.Errorf("spool: fsync: %w", err)
		}
		return s.step(name, "synced")
	}()
	if cerr := f.Close(); werr == nil && cerr != nil {
		werr = fmt.Errorf("spool: close: %w", cerr)
	}
	if werr != nil {
		return 0, werr
	}
	if err := s.root.Rename(tmp, name); err != nil {
		return 0, fmt.Errorf("spool: rename: %w", err)
	}
	if err := s.step(name, "renamed"); err != nil {
		return 0, err
	}
	return int64(len(data)), s.syncDir(path.Dir(name))
}

func (s *Spool) syncDir(dir string) error {
	if runtime.GOOS == "windows" { // no directory fsync there; the agent ships for Linux only
		return nil
	}
	d, err := s.root.Open(dir)
	if err != nil {
		return fmt.Errorf("spool: open a directory: %w", err)
	}
	defer func() { _ = d.Close() }()
	if err := d.Sync(); err != nil {
		return fmt.Errorf("spool: fsync a directory: %w", err)
	}
	return nil
}

func (s *Spool) saveManifest(j *job) error {
	b, err := wire.Encode(j.m)
	if err != nil {
		return fmt.Errorf("spool: encode a manifest: %w", err)
	}
	n, err := s.writeFile(path.Join(string(j.m.JobID), manifestName), b)
	if err != nil {
		return err
	}
	s.size += n - j.mSize
	j.mSize = n
	return nil
}

// readItem loads one item file; it must decode strictly and pass
// proto.NewResult, so only checked items are ever sent (REQ-247).
func (s *Spool) readItem(name string) (proto.Result, error) {
	b, err := s.root.ReadFile(name)
	if err != nil {
		return proto.Result{}, fmt.Errorf("spool: read an item: %w", err)
	}
	var item wire.ResultItem
	if wire.DecodeStrict(b, &item) != nil {
		return proto.Result{}, errors.New("spool: an item is unreadable")
	}
	r, err := proto.NewResult(item)
	if err != nil {
		return proto.Result{}, fmt.Errorf("spool: an item is unreadable: %w", err)
	}
	return r, nil
}

// loadJob reads one job directory: its manifest, then every item in seq
// order. Leftover .tmp files are deleted unread; other names are ignored.
func (s *Spool) loadJob(id wire.UUID) (*job, []Dropped, error) {
	var m Manifest
	b, err := s.root.ReadFile(path.Join(string(id), manifestName))
	if err != nil || wire.DecodeStrict(b, &m) != nil || m.JobID != id {
		return nil, nil, errors.New("spool: a manifest is unreadable")
	}
	j := &job{m: m, mSize: int64(len(b)), nextSeq: 1}
	ents, err := fs.ReadDir(s.root.FS(), string(id))
	if err != nil {
		return nil, nil, fmt.Errorf("spool: list a job directory: %w", err)
	}
	var bad int
	for _, e := range ents { // ReadDir sorts by name, so by seq
		name := path.Join(string(id), e.Name())
		if strings.HasSuffix(e.Name(), tmpSuffix) {
			if err := s.root.Remove(name); err != nil {
				return nil, nil, fmt.Errorf("spool: remove a temporary file: %w", err)
			}
			continue
		}
		seq, err := strconv.ParseUint(strings.TrimSuffix(e.Name(), itemSuffix), 10, 64)
		if !e.Type().IsRegular() || err != nil || e.Name() != itemName(seq) {
			continue
		}
		r, err := s.readItem(name)
		if err != nil {
			bad++
			if err := s.root.Remove(name); err != nil {
				return nil, nil, fmt.Errorf("spool: remove an unreadable item: %w", err)
			}
			continue
		}
		info, err := e.Info()
		if err != nil {
			return nil, nil, fmt.Errorf("spool: stat an item: %w", err)
		}
		j.items = append(j.items, newEntry(seq, info.Size(), r, time.Time{}))
		j.nextSeq = seq + 1
	}
	if bad > 0 {
		return j, []Dropped{{Job: id, Items: bad, Reason: "unreadable"}}, nil
	}
	return j, nil, nil
}
