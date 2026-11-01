package spool

import (
	"fmt"
	"log/slog"
	"path"
	"slices"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

// Spool overflow (TS §3.3 L226, "the oldest results are dropped first, and
// each dropped plugin is reported as ERROR spool_overflow"; #140). In order,
// until the new item fits:
//  1. the oldest full results, across jobs, become spool_overflow markers
//     under their own seq (same plugin_uuid, started_at, finished_at);
//  2. the new item itself becomes a marker;
//  3. the oldest markers (and other error items) are dropped: those plugins
//     then show as not run at the manager.
// Items in a batch being posted are never touched (#140). Manifests are
// never dropped while they hold items.

func (s *Spool) log() *slog.Logger {
	if s.Log == nil {
		return slog.Default()
	}
	return s.Log
}

// fit returns the result and encoding to store for the new item b of job j,
// after making room; ErrFull only when not even a marker fits.
func (s *Spool) fit(j *job, r proto.Result, b []byte) (proto.Result, []byte, error) {
	if s.size+int64(len(b)) <= s.max {
		return r, b, nil
	}
	if err := s.convertOldest(int64(len(b))); err != nil {
		return r, nil, err
	}
	if s.size+int64(len(b)) <= s.max {
		return r, b, nil
	}
	r = proto.OverflowMarker(r)
	b, err := wire.Encode(r.Item())
	if err != nil {
		return r, nil, fmt.Errorf("spool: marker: %w", err)
	}
	s.log().Warn("spool full: new result stored as a spool_overflow marker",
		"job_id", j.m.JobID, "plugin_uuid", r.Item().PluginUUID)
	if err := s.dropOldestMarkers(int64(len(b))); err != nil {
		return r, nil, err
	}
	if s.size+int64(len(b)) > s.max {
		return r, nil, ErrFull
	}
	return r, b, nil
}

// convertOldest rewrites the oldest full results as markers until need fits.
// A conversion that would not shrink the item is skipped.
func (s *Spool) convertOldest(need int64) error {
	for _, j := range s.jobs {
		for _, e := range j.items {
			if s.size+need <= s.max {
				return nil
			}
			if !e.full || e.flight {
				continue
			}
			name := path.Join(string(j.m.JobID), itemName(e.seq))
			r, err := s.readItem(name)
			if err != nil {
				continue // never sent anyway: Next drops it
			}
			m := proto.OverflowMarker(r)
			mb, err := wire.Encode(m.Item())
			if err != nil || int64(len(mb)) >= e.size {
				continue
			}
			n, err := s.writeFile(name, mb)
			if n > 0 { // renamed into place, even if the directory fsync failed
				s.size += n - e.size
				e.size, e.full = n, false
				s.log().Warn("spool full: oldest result replaced by a spool_overflow marker",
					"job_id", j.m.JobID, "plugin_uuid", r.Item().PluginUUID)
			}
			if err != nil {
				return err
			}
		}
	}
	return nil
}

// dropOldestMarkers removes the oldest error items (markers included) not in
// flight until need fits, and any job left empty that may go.
func (s *Spool) dropOldestMarkers(need int64) error {
	for _, j := range slices.Clone(s.jobs) {
		for _, e := range slices.Clone(j.items) {
			if s.size+need <= s.max {
				return nil
			}
			if e.flight || e.full {
				continue
			}
			var plugin wire.UUID
			if r, err := s.readItem(path.Join(string(j.m.JobID), itemName(e.seq))); err == nil {
				plugin = r.Item().PluginUUID
			}
			if err := s.removeItems(j, []uint64{e.seq}); err != nil {
				return err
			}
			s.log().Warn("spool full: spool_overflow marker dropped",
				"job_id", j.m.JobID, "plugin_uuid", plugin)
		}
		if j.removable() && !j.flight {
			if err := s.removeJob(j); err != nil {
				return err
			}
		}
	}
	return nil
}
