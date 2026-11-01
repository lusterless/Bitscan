// TP-M10-12 (tester-m10): spool overflow, REQ-248; #140; TS §3.3 L226.
// Internal test (package spool, for the crash hook).
package spool

import (
	"bytes"
	"errors"
	"fmt"
	"log/slog"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

func resAt(t *testing.T, plugin wire.UUID, stdout string, start time.Time) proto.Result {
	t.Helper()
	code := int64(1)
	r, err := proto.NewResult(wire.ResultItem{PluginUUID: plugin, ExitCode: &code, Stdout: stdout, Stderr: "e",
		StartedAt: wire.NewTime(start), FinishedAt: wire.NewTime(start.Add(2 * time.Second)), TimedOut: true, Truncated: true})
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func isMarker(it wire.ResultItem) bool {
	return it.Error != nil && *it.Error == wire.ErrSpoolOverflow && it.ExitCode == nil && it.Stdout == "" &&
		it.Stderr == "" && !it.TimedOut && !it.Truncated
}

// REQ-248 (1), (2), (3), CHK-M10-059 to -061, -364, -365: a 1 MiB spool, 30
// results of 64 KiB while the manager is down.
func TestOverflowOldestFirst(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	var logs bytes.Buffer
	s, _ := open(t, dir, 1<<20, c)
	s.Log = slog.New(slog.NewTextHandler(&logs, nil))
	if err := s.StartJob(jid(1), pids(30)); err != nil {
		t.Fatal(err)
	}
	starts := map[wire.UUID]time.Time{}
	for i := 1; i <= 30; i++ {
		st := t0.Add(time.Duration(i) * time.Minute)
		starts[pid(i)] = st
		if err := s.Put(jid(1), resAt(t, pid(i), strings.Repeat("o", 65536), st)); err != nil {
			t.Fatalf("Put %d: %v", i, err)
		}
		if s.Size() > 1<<20 || diskBytes(t, dir) > 1<<20 {
			t.Fatalf("after Put %d: size %d disk %d over 1 MiB", i, s.Size(), diskBytes(t, dir))
		}
		checkSize(t, s, dir)
	}
	_ = s.Finish(jid(1))
	var got []wire.ResultItem
	for _, b := range drain(t, s, dir) {
		for _, r := range b.Items {
			got = append(got, r.Item())
		}
	}
	if len(got) != 30 {
		t.Fatalf("%d items posted, want 30 (each exactly once)", len(got))
	}
	markers, whole := 0, 0
	lastMarker, firstWhole := 0, 31
	for i, it := range got {
		if it.PluginUUID != pid(i+1) {
			t.Fatalf("item %d is plugin %s: the order changed", i, it.PluginUUID)
		}
		if isMarker(it) {
			markers++
			lastMarker = i + 1
			if !it.StartedAt.Time().Equal(starts[it.PluginUUID]) || !it.FinishedAt.Time().Equal(starts[it.PluginUUID].Add(2*time.Second)) {
				t.Fatalf("marker %s lost its times: %v %v", it.PluginUUID, it.StartedAt.Time(), it.FinishedAt.Time())
			}
			if _, err := proto.NewResult(it); err != nil {
				t.Fatalf("marker fails NewResult: %v", err)
			}
			b, _ := wire.Encode(it)
			var back wire.ResultItem
			if err := wire.DecodeStrict(b, &back); err != nil {
				t.Fatalf("marker fails the ResultItem contract: %v", err)
			}
			continue
		}
		whole++
		firstWhole = min(firstWhole, i+1)
		if len(it.Stdout) != 65536 || it.Error != nil {
			t.Fatalf("item %d is neither whole nor a marker: %+v", i, it.Error)
		}
	}
	if markers == 0 || whole == 0 || lastMarker > firstWhole {
		t.Fatalf("markers %d (last %d), whole %d (first %d): the oldest must be markers, the newest whole", markers, lastMarker, whole, firstWhole)
	}
	if !strings.Contains(logs.String(), "spool_overflow") || strings.Contains(logs.String(), "ooooo") {
		t.Fatal("conversion not logged, or output logged")
	}
	t.Logf("RECORDED: %d markers, %d whole results", markers, whole)
}

// Across jobs: the older job's results convert first; then the newer one's.
func TestOverflowAcrossJobs(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 400_000, c)
	_ = s.StartJob(jid(1), pids(3))
	c.add(time.Second)
	_ = s.StartJob(jid(2), pids(6))
	for i := 1; i <= 3; i++ {
		_ = s.Put(jid(1), resAt(t, pid(i), strings.Repeat("a", 60000), t0))
	}
	for i := 1; i <= 3; i++ {
		_ = s.Put(jid(2), resAt(t, pid(i), strings.Repeat("b", 60000), t0))
	}
	// Room for about 6 × 60 KB; three more items of job 2 force conversions.
	for i := 4; i <= 6; i++ {
		if err := s.Put(jid(2), resAt(t, pid(i), strings.Repeat("c", 60000), t0)); err != nil {
			t.Fatal(err)
		}
		if s.Size() > 400_000 {
			t.Fatalf("size %d over the bound", s.Size())
		}
	}
	_ = s.Finish(jid(1))
	_ = s.Finish(jid(2))
	bs := drain(t, s, dir)
	kinds := map[wire.UUID][]bool{}
	for _, b := range bs {
		for _, r := range b.Items {
			kinds[b.Job] = append(kinds[b.Job], isMarker(r.Item()))
		}
	}
	if len(kinds[jid(1)]) != 3 || len(kinds[jid(2)]) != 6 {
		t.Fatalf("items posted: job 1 %d, job 2 %d", len(kinds[jid(1)]), len(kinds[jid(2)]))
	}
	anyMarker2 := false
	for _, m := range kinds[jid(2)] {
		anyMarker2 = anyMarker2 || m
	}
	// Job 1 (older) is all markers before any of job 2's results is.
	for i, m := range kinds[jid(1)] {
		if !anyMarker2 {
			break
		}
		if !m {
			t.Fatalf("job 1 item %d whole while job 2 was converted: %v / %v", i, kinds[jid(1)], kinds[jid(2)])
		}
	}
	if !kinds[jid(1)][0] {
		t.Fatalf("the oldest result (job 1 item 1) was not converted: %v / %v", kinds[jid(1)], kinds[jid(2)])
	}
	t.Logf("RECORDED: job 1 %v, job 2 %v", kinds[jid(1)], kinds[jid(2)])
}

// The new item itself becomes a marker when nothing else can make room, and
// when even markers don't fit, the oldest markers are dropped (logged).
func TestOverflowNewItemAndMarkerDrop(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	var logs bytes.Buffer
	s, _ := open(t, dir, 3000, c)
	s.Log = slog.New(slog.NewTextHandler(&logs, nil))
	_ = s.StartJob(jid(1), pids(40))
	// A result bigger than the whole spool: stored as a marker.
	if err := s.Put(jid(1), resAt(t, pid(1), strings.Repeat("x", 5000), t0)); err != nil {
		t.Fatalf("an over-size result was refused instead of stored as a marker: %v", err)
	}
	b, _ := s.Next(50, 1_572_864, 0) // the start notice
	_ = s.Ack(b)
	// Many markers into a tiny spool: the oldest are dropped, the size holds.
	for i := 2; i <= 40; i++ {
		if err := s.Put(jid(1), resAt(t, pid(i), strings.Repeat("y", 5000), t0)); err != nil && !errors.Is(err, ErrFull) {
			t.Fatal(err)
		}
		if s.Size() > 3000 {
			t.Fatalf("size %d over the bound", s.Size())
		}
		checkSize(t, s, dir)
	}
	if !strings.Contains(logs.String(), "dropped") {
		t.Fatalf("no log line for a dropped marker: %s", logs.String())
	}
	_ = s.Finish(jid(1))
	var got []wire.ResultItem
	for _, b := range drain(t, s, dir) {
		for _, r := range b.Items {
			got = append(got, r.Item())
		}
	}
	if len(got) == 0 || len(got) >= 40 {
		t.Fatalf("%d items after drops", len(got))
	}
	for _, it := range got {
		if !isMarker(it) {
			t.Fatalf("a whole result in a spool too small for one: %+v", it)
		}
	}
	if got[len(got)-1].PluginUUID != pid(40) {
		t.Fatalf("the newest marker was dropped: last is %s", got[len(got)-1].PluginUUID)
	}
}

// REQ-248 (4): an item in a batch being posted is not converted.
func TestOverflowSparesInFlight(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 300_000, c)
	_ = s.StartJob(jid(1), pids(10))
	st, _ := s.Next(50, 1_572_864, 0)
	_ = s.Ack(st)
	for i := 1; i <= 4; i++ {
		_ = s.Put(jid(1), resAt(t, pid(i), strings.Repeat("f", 65536), t0))
	}
	inflight, ok := s.Next(4, 1_572_864, 0) // all four handed out, not answered
	if !ok || len(inflight.Items) != 4 {
		t.Fatalf("in flight %d", len(inflight.Items))
	}
	// A new item that needs room: the in-flight ones can't be converted, so
	// the new item becomes a marker.
	if err := s.Put(jid(1), resAt(t, pid(5), strings.Repeat("g", 65536), t0)); err != nil {
		t.Fatal(err)
	}
	for i := range 4 {
		r, err := s.readItem(fmt.Sprintf("%s/%012d.json", jid(1), i+1))
		if err != nil || isMarker(r.Item()) {
			t.Fatalf("in-flight item %d converted mid-post (%v)", i+1, err)
		}
	}
	if err := s.Ack(inflight); err != nil {
		t.Fatal(err)
	}
	b, ok := s.Next(50, 1_572_864, 0)
	if !ok || len(b.Items) != 1 || !isMarker(b.Items[0].Item()) || b.Items[0].Item().PluginUUID != pid(5) {
		t.Fatalf("the new item: %+v", b)
	}
	_ = s.Ack(b)
	// Once answered (Ack), they're gone; after a wait answer they'd be
	// convertible again: hand out, Put without settling, then settle and
	// check a later Put can convert them.
	for i := 6; i <= 9; i++ {
		_ = s.Put(jid(1), resAt(t, pid(i), strings.Repeat("h", 65536), t0))
	}
	c.add(time.Minute)
	if err := s.Put(jid(1), resAt(t, pid(10), strings.Repeat("k", 65536), t0)); err != nil {
		t.Fatal(err)
	}
	r6, _ := s.readItem(fmt.Sprintf("%s/%012d.json", jid(1), 6))
	if !isMarker(r6.Item()) {
		t.Fatal("an item not in flight was not converted first")
	}
	checkSize(t, s, dir)
}

// CHK-M10-064: a conversion keeps the seq and is atomic: a crash during the
// conversion write leaves the old item, never a partial one.
func TestOverflowConversionAtomic(t *testing.T) {
	for _, step := range []string{"created", "written", "synced"} {
		t.Run(step, func(t *testing.T) {
			dir := filepath.Join(t.TempDir(), "spool")
			c := &clock{t: t0}
			s, _ := open(t, dir, 200_000, c)
			_ = s.StartJob(jid(1), pids(4))
			for i := 1; i <= 2; i++ {
				_ = s.Put(jid(1), resAt(t, pid(i), strings.Repeat("z", 65536), t0))
			}
			s.crash = func(file, st string) error {
				if st == step && strings.HasSuffix(file, "000000000001.json") {
					return errors.New("crash")
				}
				return nil
			}
			_ = s.Put(jid(1), resAt(t, pid(3), strings.Repeat("z", 65536), t0))
			_ = s.Close()
			s2, dropped := open(t, dir, 200_000, c)
			if len(dropped) != 0 {
				t.Fatalf("dropped %v", dropped)
			}
			r, err := s2.readItem(fmt.Sprintf("%s/%012d.json", jid(1), 1))
			if err != nil || isMarker(r.Item()) || len(r.Item().Stdout) != 65536 {
				t.Fatalf("after a crash in the conversion at %q the item is %v", step, err)
			}
			checkSize(t, s2, dir)
		})
	}
}
