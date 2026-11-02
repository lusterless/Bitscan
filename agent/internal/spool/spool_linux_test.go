// TP-M10-05 Linux rows (tester-m10): REQ-247 (6) modes and (7) symlinks.
package spool

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// REQ-247 (6): files 0600, directories 0700 (the spool directory too).
func TestP1ModesLinux(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	_ = s.StartJob(jid(1), pids(2))
	_ = s.Put(jid(1), res(t, pid(1), "x"))
	_ = s.Finish(jid(1))
	n := 0
	err := filepath.Walk(dir, func(p string, fi os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		n++
		want := os.FileMode(0o600)
		if fi.IsDir() {
			want = 0o700 | os.ModeDir
		}
		if fi.Mode() != want {
			t.Errorf("%s: mode %v, want %v", p, fi.Mode(), want)
		}
		return nil
	})
	if err != nil || n < 4 {
		t.Fatalf("walk: %v (%d entries)", err, n)
	}
}

// REQ-247 (7): a symlink planted in the spool never leads a write outside it.
func TestP1SymlinksLinux(t *testing.T) {
	outside := t.TempDir()
	victim := filepath.Join(outside, "victim")
	if err := os.WriteFile(victim, []byte("ORIGINAL"), 0o600); err != nil {
		t.Fatal(err)
	}
	check := func() {
		t.Helper()
		b, err := os.ReadFile(victim) //nolint:gosec // test path
		if err != nil || string(b) != "ORIGINAL" {
			t.Fatalf("the file outside the spool changed: %q %v", b, err)
		}
		ents, _ := os.ReadDir(outside)
		if len(ents) != 1 {
			t.Fatalf("files created outside the spool: %v", ents)
		}
	}
	// A symlinked spool directory is refused.
	link := filepath.Join(t.TempDir(), "spool")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatal(err)
	}
	if _, _, err := Open(link, 50<<20, (&clock{t: t0}).now); err == nil {
		t.Fatal("Open followed a symlinked spool directory")
	}
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	// A symlink in the place of the next item, its .tmp, and the manifest.
	_ = s.StartJob(jid(1), pids(3))
	jd := filepath.Join(dir, string(jid(1)))
	for _, name := range []string{"000000000001.json", "000000000002.json.tmp", "job.json.tmp"} {
		if err := os.Symlink(victim, filepath.Join(jd, name)); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Put(jid(1), res(t, pid(1), "one")); err != nil {
		t.Fatalf("Put over a symlink: %v", err)
	}
	if err := s.Put(jid(1), res(t, pid(2), "two")); err != nil {
		t.Fatalf("Put over a symlinked .tmp: %v", err)
	}
	if err := s.Finish(jid(1)); err != nil {
		t.Fatalf("Finish over a symlinked manifest .tmp: %v", err)
	}
	check()
	// The manifest itself replaced by a symlink, and a symlinked job directory
	// planted beside it: Open neither follows nor writes through them.
	_ = s.Close()
	if err := os.Remove(filepath.Join(jd, "job.json")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(victim, filepath.Join(jd, "job.json")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(dir, string(jid(2)))); err != nil {
		t.Fatal(err)
	}
	s2, dropped, err := Open(dir, 50<<20, c.now)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer func() { _ = s2.Close() }()
	t.Logf("RECORDED: dropped at Open %v", dropped)
	check()
	if s2.StartJob(jid(2), pids(1)) == nil {
		t.Log("RECORDED: StartJob replaced the symlinked job directory")
	}
	check()
	for _, b := range drain(t, s2, dir) {
		for _, r := range b.Items {
			if strings.Contains(r.Item().Stdout, "ORIGINAL") {
				t.Fatal("the outside file was read as an item")
			}
		}
	}
	_ = time.Second
}
