// Tests for the state directory (TS §3.1 L162, §3.2 L183–L184, §3.3 L212,
// §3.7 file table; REQ-093; tests/m4/test-plan.md TP-M4-03, CHK-M4-030 to
// -038; mutation rows CHK-M4-333, -334, -340). Linux only: modes, umask and
// the directory fsync need it. In-package so the crash seam can be set.
package state

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/wire"
)

const (
	tokA = wire.AgentToken("bsa_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
	tokB = wire.AgentToken("bsa_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB")
	id1  = wire.UUID("6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b")
)

var (
	t0     = time.Date(2026, 1, 10, 8, 0, 0, 0, time.UTC)
	tA     = Token{Value: tokA, IssuedAt: t0, ExpiresAt: t0.Add(365 * 24 * time.Hour)}
	tB     = Token{Value: tokB, IssuedAt: t0.Add(335 * 24 * time.Hour), ExpiresAt: t0.Add(700 * 24 * time.Hour)}
	steps  = []string{"created", "written", "synced", "renamed"}
	errBoo = errors.New("injected crash")
)

func stateDir(t *testing.T) string {
	t.Helper()
	parent := t.TempDir()
	dir := filepath.Join(parent, "bitscan-agent")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	return dir
}

func open(t *testing.T, dir string) *Store {
	t.Helper()
	s, err := Open(dir)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s
}

func mode(t *testing.T, p string) (os.FileMode, uint32) {
	t.Helper()
	st, err := os.Lstat(p)
	if err != nil {
		t.Fatalf("stat %s: %v", p, err)
	}
	return st.Mode(), st.Sys().(*syscall.Stat_t).Uid
}

func noTmp(t *testing.T, dir string) {
	t.Helper()
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".tmp") {
			t.Errorf("temporary file left: %s", e.Name())
		}
	}
}

// CHK-M4-030 (CHK-M4-340): modes and owner regardless of the umask; exact contents.
func TestModesWhateverTheUmask(t *testing.T) {
	for _, um := range []int{0o000, 0o022, 0o077, 0o777} {
		t.Run(fmt.Sprintf("umask %04o", um), func(t *testing.T) {
			// The directory exists before the umask is set, as postinst creates
			// it (0700); a non-root user cannot create t.TempDir under 0777.
			dir := stateDir(t)
			old := syscall.Umask(um)
			defer syscall.Umask(old)
			s := open(t, dir)
			if err := s.SaveEnrolment(wire.UUID(strings.ToUpper(string(id1))), tA); err != nil {
				t.Fatalf("SaveEnrolment: %v", err)
			}
			want := map[string]os.FileMode{"agent_id": 0o644, "token": 0o600, "token.json": 0o600}
			for name, m := range want {
				got, uid := mode(t, filepath.Join(dir, name))
				if got.Perm() != m || !got.IsRegular() {
					t.Errorf("%s mode %v, want %04o regular", name, got, m)
				}
				if fmt.Sprint(uid) != fmt.Sprint(os.Getuid()) {
					t.Errorf("%s owner uid %d, want %d", name, uid, os.Getuid())
				}
			}
			b := readFile(t, filepath.Join(dir, "agent_id"))
			if string(b) != string(id1)+"\n" {
				t.Errorf("agent_id content %q", b)
			}
			b = readFile(t, filepath.Join(dir, "token"))
			if string(b) != string(tokA)+"\n" {
				t.Errorf("token content wrong (len %d)", len(b))
			}
			if err := s.Add0(); err != nil {
				t.Fatal(err)
			}
			got, _ := mode(t, filepath.Join(dir, "seen_jobs.json"))
			if got.Perm() != 0o600 {
				t.Errorf("seen_jobs.json mode %v, want 0600", got)
			}
			noTmp(t, dir)
		})
	}
}

// Add0 records one seen id (test helper).
func (s *Store) Add0() error {
	j, err := s.LoadSeen(func() time.Time { return t0 })
	if err != nil {
		return err
	}
	return j.Add(id1)
}

func TestReadBack(t *testing.T) {
	dir := stateDir(t)
	s := open(t, dir)
	if _, err := s.AgentID(); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("AgentID with no file: %v, want ErrNotExist", err)
	}
	if _, err := s.Token(); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("Token with no file: %v, want ErrNotExist", err)
	}
	if _, err := s.EnrolToken(); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("EnrolToken with no file: %v, want ErrNotExist", err)
	}
	if err := s.SaveEnrolment(id1, tA); err != nil {
		t.Fatal(err)
	}
	s2 := open(t, dir)
	id, err := s2.AgentID()
	if err != nil || id != id1 {
		t.Fatalf("AgentID %q, %v", id, err)
	}
	tok, err := s2.Token()
	if err != nil || tok.Value != tokA || !tok.TimesKnown || !tok.IssuedAt.Equal(tA.IssuedAt) || !tok.ExpiresAt.Equal(tA.ExpiresAt) {
		t.Fatalf("Token %+v, %v", tok, err)
	}
	// malformed files are errors with fixed words, never their content
	for _, c := range []struct{ name, content string }{
		{"agent_id", "CANARY-not-a-uuid\n"},
		{"token", "bsa_" + "CANARY\n"},
		{"token.json", "{CANARY"},
	} {
		name, content := c.name, c.content
		dir := stateDir(t)
		s := open(t, dir)
		if name != "agent_id" {
			_ = s.SaveEnrolment(id1, tA)
		}
		if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
		var rerr error
		if name == "agent_id" {
			_, rerr = s.AgentID()
		} else {
			_, rerr = s.Token()
		}
		if rerr == nil || strings.Contains(rerr.Error(), "CANARY") {
			t.Errorf("malformed %s: %v", name, rerr)
		}
	}
}

// CHK-M4-031: a crash after any step of a token rotation leaves the old or the
// new complete state (TimesKnown false only for the new token whose times
// file was not yet replaced), never a partial file, and the next save works.
func TestCrashAtEveryStepOfARotation(t *testing.T) {
	for _, file := range []string{"token", "token.json"} {
		for _, step := range steps {
			t.Run(file+":"+step, func(t *testing.T) {
				dir := stateDir(t)
				s := open(t, dir)
				if err := s.SaveEnrolment(id1, tA); err != nil {
					t.Fatal(err)
				}
				s.crash = func(f, st string) error {
					if f == file && st == step {
						return errBoo
					}
					return nil
				}
				if err := s.SaveToken(tB); !errors.Is(err, errBoo) {
					t.Fatalf("SaveToken error %v, want the injected crash", err)
				}
				// "restart": a new Store on the same directory
				r := open(t, dir)
				got, err := r.Token()
				if err != nil {
					t.Fatalf("Token after crash: %v", err)
				}
				switch got.Value {
				case tokA:
					if !got.TimesKnown || !got.IssuedAt.Equal(tA.IssuedAt) || !got.ExpiresAt.Equal(tA.ExpiresAt) {
						t.Errorf("old token with wrong times: %+v", got)
					}
				case tokB:
					if got.TimesKnown && (!got.IssuedAt.Equal(tB.IssuedAt) || !got.ExpiresAt.Equal(tB.ExpiresAt)) {
						t.Errorf("new token reported with the old token's times: %+v", got)
					}
				default:
					t.Fatalf("token is neither old nor new (partial?): len %d", len(got.Value))
				}
				// which state each crash point must give
				wantNew := file == "token.json" || step == "renamed"
				if (got.Value == tokB) != wantNew {
					t.Errorf("crash after %s:%s gave token %v, want new=%v", file, step, got.Value == tokB, wantNew)
				}
				if file == "token.json" && step == "renamed" && !got.TimesKnown {
					t.Error("token.json renamed but times unknown")
				}
				id, err := r.AgentID()
				if err != nil || id != id1 {
					t.Errorf("agent_id damaged: %q %v", id, err)
				}
				// the next save works and leaves no temporary file
				if err := r.SaveToken(tB); err != nil {
					t.Fatalf("save after crash: %v", err)
				}
				got, _ = r.Token()
				if got.Value != tokB || !got.TimesKnown || !got.IssuedAt.Equal(tB.IssuedAt) {
					t.Errorf("after recovery %+v", got)
				}
				noTmp(t, dir)
			})
		}
	}
}

// Every write of every file is atomic: a crash at any step of agent_id or
// seen_jobs.json leaves the previous complete content.
func TestCrashLeavesPreviousContent(t *testing.T) {
	id2 := wire.UUID("11111111-2222-4333-8444-555555555555")
	for _, step := range steps[:3] {
		t.Run("agent_id:"+step, func(t *testing.T) {
			dir := stateDir(t)
			s := open(t, dir)
			if err := s.SaveEnrolment(id1, tA); err != nil {
				t.Fatal(err)
			}
			s.crash = func(f, st string) error {
				if f == "agent_id" && st == step {
					return errBoo
				}
				return nil
			}
			if err := s.SaveEnrolment(id2, tB); !errors.Is(err, errBoo) {
				t.Fatalf("error %v", err)
			}
			r := open(t, dir)
			if id, err := r.AgentID(); err != nil || id != id1 {
				t.Errorf("agent_id %q %v, want the old one", id, err)
			}
			if tok, _ := r.Token(); tok.Value != tokA {
				t.Error("token changed although the enrolment write stopped at agent_id")
			}
		})
		t.Run("seen_jobs.json:"+step, func(t *testing.T) {
			dir := stateDir(t)
			s := open(t, dir)
			j, _ := s.LoadSeen(func() time.Time { return t0 })
			if err := j.Add(id1); err != nil {
				t.Fatal(err)
			}
			s.crash = func(f, st string) error {
				if f == "seen_jobs.json" && st == step {
					return errBoo
				}
				return nil
			}
			if err := j.Add(id2); err == nil {
				t.Fatal("Add reported success although its write crashed")
			}
			if !j.Has(id2) {
				t.Error("an id whose write failed is not treated as seen in memory (must fail closed)")
			}
			r := open(t, dir)
			j2, err := r.LoadSeen(func() time.Time { return t0 })
			if err != nil {
				t.Fatalf("reload after crash: %v", err)
			}
			if !j2.Has(id1) {
				t.Error("the earlier id was lost")
			}
		})
	}
}

// CHK-M4-032: symlinks are never followed out of the directory.
func TestSymlinksDoNotLeadOutside(t *testing.T) {
	outside := filepath.Join(t.TempDir(), "outside")
	if err := os.WriteFile(outside, []byte(string(id1)+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"token", ".token.tmp", "agent_id", ".agent_id.tmp", "token.json", "seen_jobs.json"} {
		t.Run("write over "+name, func(t *testing.T) {
			dir := stateDir(t)
			if err := os.Symlink(outside, filepath.Join(dir, name)); err != nil {
				t.Fatal(err)
			}
			s := open(t, dir)
			_ = s.SaveEnrolment(id1, tA)
			_ = s.Add0()
			b := readFile(t, outside)
			if string(b) != string(id1)+"\n" {
				t.Fatalf("the file outside the directory was changed: %q", b)
			}
		})
	}
	t.Run("read through agent_id symlink", func(t *testing.T) {
		dir := stateDir(t)
		if err := os.Symlink(outside, filepath.Join(dir, "agent_id")); err != nil {
			t.Fatal(err)
		}
		s := open(t, dir)
		if id, err := s.AgentID(); err == nil {
			t.Fatalf("AgentID read %q through a symlink leading outside", id)
		}
	})
	t.Run("stale tmp file", func(t *testing.T) {
		dir := stateDir(t)
		if err := os.WriteFile(filepath.Join(dir, ".token.tmp"), []byte("partial"), 0o600); err != nil {
			t.Fatal(err)
		}
		s := open(t, dir)
		if err := s.SaveEnrolment(id1, tA); err != nil {
			t.Fatalf("a stale .token.tmp blocked the write: %v", err)
		}
		noTmp(t, dir)
	})
}

// CHK-M4-033: enroll.token is read and deleted; deleting twice is fine.
func TestEnrolToken(t *testing.T) {
	dir := stateDir(t)
	if err := os.WriteFile(filepath.Join(dir, "enroll.token"), []byte("bse_CANARYbody\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	s := open(t, dir)
	tok, err := s.EnrolToken()
	if err != nil || tok != "bse_CANARYbody" {
		t.Fatalf("EnrolToken %q, %v", tok, err)
	}
	if err := s.SaveEnrolment(id1, tA); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "enroll.token")); err != nil {
		t.Fatal("SaveEnrolment removed enroll.token (TASK-098 deletes it after the save)")
	}
	if err := s.DeleteEnrolToken(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "enroll.token")); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("enroll.token still there: %v", err)
	}
	if err := s.DeleteEnrolToken(); err != nil {
		t.Fatalf("second delete: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "enroll.token"), []byte(" \n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.EnrolToken(); err == nil {
		t.Fatal("an empty enroll.token was accepted")
	}
}

// CHK-M4-034 (CHK-M4-333, -334): seen ids survive a restart and expire after
// 7 days on the given clock; a corrupt file refuses start-up.
func TestSeenIDs(t *testing.T) {
	dir := stateDir(t)
	now := t0
	clock := func() time.Time { return now }
	s := open(t, dir)
	j, err := s.LoadSeen(clock)
	if err != nil {
		t.Fatal(err)
	}
	if j.Has(id1) {
		t.Fatal("empty set has the id")
	}
	if err := j.Add(id1); err != nil {
		t.Fatal(err)
	}
	if !j.Has(wire.UUID(strings.ToUpper(string(id1)))) {
		t.Error("upper-case lookup of a seen id failed")
	}
	if SeenFor != 7*24*time.Hour {
		t.Fatalf("SeenFor %v", SeenFor)
	}
	for _, c := range []struct {
		at   time.Duration
		seen bool
	}{
		{time.Second, true},
		{6 * 24 * time.Hour, true},
		{7*24*time.Hour - time.Second, true},
		{7*24*time.Hour + time.Second, false},
		{30 * 24 * time.Hour, false},
	} {
		now = t0.Add(c.at)
		// restart: a new Store and a reload from disk
		r := open(t, dir)
		j2, err := r.LoadSeen(clock)
		if err != nil {
			t.Fatal(err)
		}
		if j2.Has(id1) != c.seen {
			t.Errorf("after %v (restart): Has = %v, want %v", c.at, !c.seen, c.seen)
		}
		if j.Has(id1) != c.seen {
			t.Errorf("after %v (same process): Has = %v, want %v", c.at, !c.seen, c.seen)
		}
	}
	// pruned from the file on the next write
	now = t0.Add(8 * 24 * time.Hour)
	j3, _ := open(t, dir).LoadSeen(clock)
	id2 := wire.UUID("11111111-2222-4333-8444-555555555555")
	if err := j3.Add(id2); err != nil {
		t.Fatal(err)
	}
	b := readFile(t, filepath.Join(dir, "seen_jobs.json"))
	if strings.Contains(string(b), string(id1)) || !strings.Contains(string(b), string(id2)) {
		t.Errorf("seen_jobs.json after prune: %s", b)
	}
	// re-adding keeps the first-seen time (the window is not extended)
	now = t0.Add(9 * 24 * time.Hour)
	if err := j3.Add(id2); err != nil {
		t.Fatal(err)
	}
	now = t0.Add(8*24*time.Hour + 7*24*time.Hour + time.Second)
	if j3.Has(id2) {
		t.Error("re-adding an id moved its first-seen time")
	}
	if err := j3.Add("not-a-uuid"); err == nil {
		t.Error("a non-UUID job id was recorded")
	}
}

func TestCorruptSeenFileRefusesStart(t *testing.T) {
	for name, content := range map[string]string{
		"bad json":   "{bad",
		"null":       "null",
		"array":      "[]",
		"bad key":    `{"not-a-uuid":"2026-01-10T08:00:00Z"}`,
		"bad time":   `{"6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b":"yesterday"}`,
		"empty file": "",
		"truncated":  `{"6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b":"2026-01-10T08:00`,
	} {
		t.Run(name, func(t *testing.T) {
			dir := stateDir(t)
			if err := os.WriteFile(filepath.Join(dir, "seen_jobs.json"), []byte(content), 0o600); err != nil {
				t.Fatal(err)
			}
			if _, err := open(t, dir).LoadSeen(func() time.Time { return t0 }); err == nil {
				t.Fatal("a corrupt seen_jobs.json was accepted (a replay would be possible)")
			}
		})
	}
	t.Run("unreadable (non-root)", func(t *testing.T) {
		if os.Geteuid() == 0 {
			t.Skip("named skip: root reads mode-0000 files; this case runs in the bstester run")
		}
		dir := stateDir(t)
		if err := os.WriteFile(filepath.Join(dir, "seen_jobs.json"), []byte("{}"), 0o000); err != nil {
			t.Fatal(err)
		}
		if _, err := open(t, dir).LoadSeen(func() time.Time { return t0 }); err == nil {
			t.Fatal("an unreadable seen_jobs.json was accepted")
		}
	})
	t.Run("empty object is an empty set", func(t *testing.T) {
		dir := stateDir(t)
		_ = os.WriteFile(filepath.Join(dir, "seen_jobs.json"), []byte("{}"), 0o600)
		if _, err := open(t, dir).LoadSeen(func() time.Time { return t0 }); err != nil {
			t.Fatal(err)
		}
	})
}

// CHK-M4-035: many ids stay bounded by the 7-day window.
func TestSeenManyIDs(t *testing.T) {
	dir := stateDir(t)
	now := t0
	j, _ := open(t, dir).LoadSeen(func() time.Time { return now })
	for i := range 1000 {
		now = t0.Add(time.Duration(i) * time.Hour) // about 41 days
		if err := j.Add(wire.UUID(fmt.Sprintf("00000000-0000-4000-8000-%012d", i))); err != nil {
			t.Fatal(err)
		}
	}
	b := readFile(t, filepath.Join(dir, "seen_jobs.json"))
	n := strings.Count(string(b), "-4000-8000-")
	if n < 167 || n > 169 { // ids of the last 7 days = 168 hours
		t.Errorf("%d ids kept, want about 168", n)
	}
}

// CHK-M4-036: no write goes outside the directory, and no temporary file
// is made elsewhere (a read-only TMPDIR and a read-only parent).
func TestNothingWrittenOutside(t *testing.T) {
	parent := t.TempDir()
	dir := filepath.Join(parent, "state")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	ro := filepath.Join(parent, "ro-tmp")
	if err := os.Mkdir(ro, 0o500); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TMPDIR", ro)
	before := listTree(t, parent)
	s := open(t, dir)
	if err := s.SaveEnrolment(id1, tA); err != nil {
		t.Fatal(err)
	}
	if err := s.SaveToken(tB); err != nil {
		t.Fatal(err)
	}
	if err := s.Add0(); err != nil {
		t.Fatal(err)
	}
	if err := s.DeleteEnrolToken(); err != nil {
		t.Fatal(err)
	}
	after := listTree(t, parent)
	for p := range after {
		if !strings.HasPrefix(p, dir+string(os.PathSeparator)) && !before[p] {
			t.Errorf("created outside the state directory: %s", p)
		}
	}
	// static: the package makes no temporary file of its own and opens nothing by path
	for _, fn := range []string{"state.go", "seen.go"} {
		src, err := os.ReadFile(filepath.Clean(fn))
		if err != nil {
			t.Fatal(err)
		}
		for _, bad := range []string{"os.CreateTemp", "os.TempDir", "os.WriteFile", "os.OpenFile(", "os.Create(", "os.Rename(", "os.Remove("} {
			if strings.Contains(string(src), bad) {
				t.Errorf("%s uses %s outside os.Root", fn, bad)
			}
		}
	}
}

func listTree(t *testing.T, root string) map[string]bool {
	t.Helper()
	out := map[string]bool{}
	_ = filepath.WalkDir(root, func(p string, _ os.DirEntry, err error) error {
		if err == nil {
			out[p] = true
		}
		return nil
	})
	return out
}

// CHK-M4-037: concurrent token saves and seen-id adds leave complete files.
func TestConcurrentWrites(t *testing.T) {
	dir := stateDir(t)
	s := open(t, dir)
	if err := s.SaveEnrolment(id1, tA); err != nil {
		t.Fatal(err)
	}
	j, _ := s.LoadSeen(func() time.Time { return t0 })
	var wg sync.WaitGroup
	errs := make(chan error, 1000)
	for g := range 8 {
		wg.Add(2)
		go func() {
			defer wg.Done()
			for i := range 25 {
				tok := tA
				if (g+i)%2 == 0 {
					tok = tB
				}
				if err := s.SaveToken(tok); err != nil {
					errs <- err
				}
			}
		}()
		go func() {
			defer wg.Done()
			for i := range 25 {
				if err := j.Add(wire.UUID(fmt.Sprintf("00000000-0000-4000-8%03d-%012d", g, i))); err != nil {
					errs <- err
				}
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Errorf("concurrent write: %v", err)
	}
	tok, err := open(t, dir).Token()
	if err != nil || (tok.Value != tokA && tok.Value != tokB) || !tok.TimesKnown {
		t.Fatalf("after concurrent saves: %+v %v", tok, err)
	}
	want := tA
	if tok.Value == tokB {
		want = tB
	}
	if !tok.IssuedAt.Equal(want.IssuedAt) {
		t.Errorf("token and token.json from different saves: %+v", tok)
	}
	j2, err := open(t, dir).LoadSeen(func() time.Time { return t0 })
	if err != nil {
		t.Fatal(err)
	}
	for g := range 8 {
		for i := range 25 {
			if !j2.Has(wire.UUID(fmt.Sprintf("00000000-0000-4000-8%03d-%012d", g, i))) {
				t.Fatalf("seen id %d/%d lost", g, i)
			}
		}
	}
	noTmp(t, dir)
}

// CHK-M4-037: the store's own write lock. Writes of one file not covered by
// the token or seen locks (agent_id via SaveEnrolment, enroll.token deletes)
// from several goroutines never collide on the temporary name.
func TestConcurrentSameFileWrites(t *testing.T) {
	dir := stateDir(t)
	s := open(t, dir)
	var wg sync.WaitGroup
	errs := make(chan error, 1000)
	for g := range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range 20 {
				tok := tA
				if (g+i)%2 == 0 {
					tok = tB
				}
				if err := s.SaveEnrolment(id1, tok); err != nil {
					errs <- err
				}
				if err := s.DeleteEnrolToken(); err != nil {
					errs <- err
				}
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Errorf("concurrent SaveEnrolment: %v", err)
	}
	if id, err := s.AgentID(); err != nil || id != id1 {
		t.Fatalf("agent_id after concurrent saves: %q %v", id, err)
	}
	noTmp(t, dir)
}

// CHK-M4-038: no token in any error or formatted value.
func TestTokenNeverInErrorsOrOutput(t *testing.T) {
	dir := stateDir(t)
	s := open(t, dir)
	bad := Token{Value: "bsa_CANARY_too_short"}
	if err := s.SaveToken(bad); err == nil || strings.Contains(err.Error(), "CANARY") {
		t.Errorf("invalid token save: %v", err)
	}
	canary := Token{Value: wire.AgentToken("bsa_" + strings.Repeat("CANARY", 7) + "C")}
	if len(canary.Value) != 47 {
		t.Fatalf("canary length %d", len(canary.Value))
	}
	if err := s.SaveToken(canary); err != nil {
		t.Fatal(err)
	}
	for _, verb := range []string{"%v", "%+v", "%#v", "%s"} {
		got, _ := s.Token()
		if out := fmt.Sprintf(verb, got); strings.Contains(out, "CANARY") {
			t.Errorf("%s prints the token: %s", verb, out)
		}
	}
	// an unwritable directory: the error has no token
	if err := syscall.Chmod(dir, 0o500); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = syscall.Chmod(dir, 0o700) }()
	if os.Geteuid() != 0 {
		if err := s.SaveToken(canary); err == nil || strings.Contains(err.Error(), "CANARY") {
			t.Errorf("save into a read-only directory: %v", err)
		}
	}
	// token.json never holds the token itself
	b := readFile(t, filepath.Join(dir, "token.json"))
	if strings.Contains(string(b), "CANARY") {
		t.Error("token.json holds the token")
	}
}

func readFile(t *testing.T, p string) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Clean(p))
	if err != nil {
		t.Fatalf("read %s: %v", p, err)
	}
	return b
}
