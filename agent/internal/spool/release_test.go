// TASK-212 r1 delta (tester-m10c): Spool.Release, decisions "#140 reading:
// in-flight protection covers only an outstanding HTTP attempt". Release
// only clears the in-flight mark: no file, size or manifest changes; a batch
// never handed out (or already settled) is an error; a released batch's
// items can be converted by overflow again, and the next Next is a fresh
// batch. Portable (Windows and Linux).
package spool

import (
	"crypto/sha256"
	"encoding/hex"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"
)

// snapshot is every file under dir with its content hash.
func snapshot(t *testing.T, dir string) string {
	t.Helper()
	var lines []string
	err := filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		b, err := os.ReadFile(p) //nolint:gosec // the test's own temp dir
		if err != nil {
			return err
		}
		h := sha256.Sum256(b)
		rel, _ := filepath.Rel(dir, p)
		lines = append(lines, filepath.ToSlash(rel)+" "+hex.EncodeToString(h[:8]))
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n")
}

func TestReleaseOnlyClearsInFlight(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	if err := s.StartJob(jid(1), pids(3)); err != nil {
		t.Fatal(err)
	}
	// The start notice: released, it is handed out again (not acked).
	st, ok := s.Next(50, 1_572_864, 0)
	if !ok || !st.Start {
		t.Fatalf("first batch %s, want the start notice", describe([]Batch{st}))
	}
	before := snapshot(t, dir)
	size := s.Size()
	if err := s.Release(st); err != nil {
		t.Fatalf("Release of the start notice: %v", err)
	}
	if snapshot(t, dir) != before || s.Size() != size {
		t.Fatal("Release changed files, the manifest or the size")
	}
	st2, ok := s.Next(50, 1_572_864, 0)
	if !ok || !st2.Start {
		t.Fatalf("after Release: %s, want the start notice again (StartAcked must stay false)", describe([]Batch{st2}))
	}
	if err := s.Ack(st2); err != nil {
		t.Fatal(err)
	}
	for i := 1; i <= 3; i++ {
		if err := s.Put(jid(1), res(t, pid(i), "out")); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Finish(jid(1)); err != nil {
		t.Fatal(err)
	}
	b, ok := s.Next(50, 1_572_864, 0)
	if !ok || len(b.Items) != 3 || !b.Final {
		t.Fatalf("batch %s, want 3 items with final", describe([]Batch{b}))
	}
	before, size = snapshot(t, dir), s.Size()
	if err := s.Release(b); err != nil {
		t.Fatal(err)
	}
	if snapshot(t, dir) != before || s.Size() != size {
		t.Fatal("Release of an item batch changed files, the manifest or the size")
	}
	checkSize(t, s, dir)
	// The same items again, as a fresh batch; FinalAcked was not set.
	b2, ok := s.Next(50, 1_572_864, 0)
	if !ok || describe([]Batch{b2}) != describe([]Batch{b}) {
		t.Fatalf("after Release: %s, want %s again", describe([]Batch{b2}), describe([]Batch{b}))
	}
	// Settled batches can't be released, and nothing is handed out twice.
	if err := s.Ack(b2); err != nil {
		t.Fatal(err)
	}
	if err := s.Release(b2); err == nil {
		t.Fatal("Release of an acked batch: no error")
	}
	if _, ok := s.Next(50, 1_572_864, 0); ok {
		t.Fatal("a batch after the final was acked")
	}
}

func TestReleaseOfABatchNeverHandedOut(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	if err := s.Release(Batch{Job: jid(9)}); err == nil {
		t.Fatal("Release of an unknown job's batch: no error")
	}
	if err := s.StartJob(jid(1), pids(2)); err != nil {
		t.Fatal(err)
	}
	before := snapshot(t, dir)
	if err := s.Release(Batch{Job: jid(1), Start: true}); err == nil {
		t.Fatal("Release of a start notice never handed out: no error")
	}
	b, _ := s.Next(50, 1_572_864, 0)
	if err := s.Release(b); err != nil {
		t.Fatal(err)
	}
	if err := s.Release(b); err == nil {
		t.Fatal("a second Release of the same batch: no error")
	}
	if snapshot(t, dir) != before {
		t.Fatal("refused Releases changed the spool")
	}
}

// After a failed attempt the batch is released, so a Put that needs room
// converts those (oldest) items, and the next batch carries the markers:
// the retry is a fresh body, never the old one.
func TestReleasedItemsConvertible(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 300_000, c)
	_ = s.StartJob(jid(1), pids(8))
	st, _ := s.Next(50, 1_572_864, 0)
	_ = s.Ack(st)
	for i := 1; i <= 4; i++ {
		_ = s.Put(jid(1), resAt(t, pid(i), strings.Repeat("f", 65536), t0))
	}
	out, ok := s.Next(4, 1_572_864, 0) // the attempt
	if !ok || len(out.Items) != 4 {
		t.Fatalf("attempt %d items", len(out.Items))
	}
	if err := s.Release(out); err != nil { // the attempt failed (503)
		t.Fatal(err)
	}
	c.add(time.Second)
	if err := s.Put(jid(1), resAt(t, pid(5), strings.Repeat("g", 65536), t0)); err != nil {
		t.Fatal(err)
	}
	if s.Size() > 300_000 {
		t.Fatalf("size %d over the bound", s.Size())
	}
	retry, ok := s.Next(50, 1_572_864, 0)
	if !ok || len(retry.Items) != 5 {
		t.Fatalf("retry %s", describe([]Batch{retry}))
	}
	if !isMarker(retry.Items[0].Item()) {
		t.Fatal("the oldest released item was not converted: the retry would resend the old body")
	}
	if isMarker(retry.Items[4].Item()) {
		t.Fatal("the newest item became the marker (inverted order, REQ-248 (1))")
	}
	checkSize(t, s, dir)
}
