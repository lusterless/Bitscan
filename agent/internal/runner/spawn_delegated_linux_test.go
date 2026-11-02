//go:build linux && delegated

// TP-M10-15 delegated rows (tester-m10): plugin start, REQ-239 (1)–(5), (7),
// REQ-238 (3), #135 (a), #136 (a)–(c); TASK-221 r1 (confined chmod). Run in
// the delegated binary as bitscan-runner (see cgroup_delegated_linux_test.go)
// with PrivateTmp=yes. Harmless payloads only.
package runner

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

var (
	cgOnce sync.Once
	cgOpen *Cgroups
	cgErr  error
)

// TestMain holds the main OS thread (m0) for the main goroutine, as
// cmd/bitscan-runner's init does (TASK-221 r2, decisions "keep the main OS
// thread out of Spawn"). Without it Spawn's locked goroutine can run on m0,
// which the Go runtime parks forever at niceness 10 instead of ending it.
func TestMain(m *testing.M) {
	runtime.LockOSThread()
	os.Exit(m.Run())
}

// threadNiceness lists every thread of this process with its niceness
// (field 19 of /proc/self/task/<tid>/stat), its state and whether it is m0.
func threadNiceness(t *testing.T) (bad []string) {
	t.Helper()
	ents, err := os.ReadDir("/proc/self/task")
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range ents {
		b, err := os.ReadFile("/proc/self/task/" + e.Name() + "/stat")
		if err != nil {
			continue // the thread ended
		}
		f := strings.Fields(string(b)[strings.LastIndex(string(b), ")")+2:])
		tid, _ := strconv.Atoi(e.Name())
		// ioprio_get(IOPRIO_WHO_PROCESS, tid): the class is in bits 13+.
		prio, _, errno := unix.Syscall(unix.SYS_IOPRIO_GET, 1, uintptr(tid), 0)
		idle := errno == 0 && prio>>13 == 3
		if (len(f) > 16 && f[16] != "0") || idle {
			m0 := ""
			if tid == os.Getpid() {
				m0 = " (m0, the main thread)"
			}
			bad = append(bad, fmt.Sprintf("thread %s%s state %s niceness %s ioprio-idle %v", e.Name(), m0, f[0], f[16], idle))
		}
	}
	return bad
}

// sharedCgroups opens the delegated cgroup once per test binary.
func sharedCgroups(t *testing.T) *Cgroups {
	t.Helper()
	cgOnce.Do(func() { cgOpen, cgErr = Open(slog.New(slog.NewTextHandler(os.Stderr, nil))) })
	if cgErr != nil {
		t.Fatalf("Open: %v", cgErr)
	}
	return cgOpen
}

// runPlugin spawns execute in a fresh plugin cgroup, reads both streams,
// waits, kills and removes the cgroup, and returns stdout, stderr, exit.
func runPlugin(t *testing.T, c *Cgroups, execute string) (string, string, int64, *Spawned) {
	t.Helper()
	p, err := c.NewPlugin()
	if err != nil {
		t.Fatal(err)
	}
	s, err := Spawn(p, execute, time.Now)
	if err != nil {
		t.Fatalf("Spawn: %v", err)
	}
	var wg sync.WaitGroup
	var out, errb []byte
	wg.Add(2)
	go func() { defer wg.Done(); out, _ = io.ReadAll(s.Stdout) }()
	go func() { defer wg.Done(); errb, _ = io.ReadAll(s.Stderr) }()
	ws, err := s.Wait()
	if err != nil {
		t.Fatal(err)
	}
	if err := p.Kill(); err != nil {
		t.Fatal(err)
	}
	wg.Wait()
	_ = p.WaitEmpty(t.Context())
	if err := p.Remove(); err != nil {
		t.Fatal(err)
	}
	_ = s.Stdout.Close()
	_ = s.Stderr.Close()
	return string(out), string(errb), ExitCode(ws), s
}

func field(out, key string) string {
	for _, l := range strings.Split(out, "\n") {
		if v, ok := strings.CutPrefix(l, key+"="); ok {
			return v
		}
	}
	return "<missing " + key + ">"
}

func TestDelegatedSpawn(t *testing.T) {
	c := sharedCgroups(t)
	recordIdentity(t)
	t.Run("environment, descriptors, directory, argv, uid (REQ-239 (1), (2), (4), (5), (7))", func(t *testing.T) {
		// The fd list is printed straight to stdout between markers: a
		// redirection would make dash hold fd 10 (its saved stdout) while ls
		// runs, and $(...) would add the substitution pipe.
		exe := `echo LS=$(ls -A | wc -l); echo FDSBEGIN; ls /proc/$$/fd; echo FDSEND;` +
			` printf 'ENV='; tr '\0' '|' < /proc/$$/environ; echo; echo FD0=$(readlink /proc/$$/fd/0);` +
			` echo PWD=$(pwd); echo MODE=$(stat -c %a .); printf 'ARGV=%s\n' "$(tr '\0' '|' < /proc/$$/cmdline)"; echo UID=$(id -u)`
		out, errb, code, s := runPlugin(t, c, exe)
		if code != 0 || errb != "" {
			t.Fatalf("exit %d stderr %q", code, errb)
		}
		fds := ""
		if i, j := strings.Index(out, "FDSBEGIN\n"), strings.Index(out, "FDSEND"); i >= 0 && j > i {
			fds = strings.Join(strings.Fields(out[i+len("FDSBEGIN\n"):j]), ",")
		}
		if fds != "0,1,2" {
			t.Errorf("the plugin shell's descriptors: %q, want 0,1,2", fds)
		}
		checks := map[string]string{
			"LS":   "0",
			"ENV":  "PATH=/usr/sbin:/usr/bin:/sbin:/bin|",
			"FD0":  "/dev/null",
			"MODE": "700",
			"ARGV": "/bin/sh|-c|" + exe + "|",
			"UID":  strconv.Itoa(os.Getuid()),
		}
		for k, want := range checks {
			if got := field(out, k); got != want {
				t.Errorf("%s = %q, want %q", k, got, want)
			}
		}
		if pwd := field(out, "PWD"); !strings.HasPrefix(pwd, "/tmp/bitscan-p-") || pwd != s.TempDir {
			t.Errorf("PWD %q (temp dir %q)", pwd, s.TempDir)
		}
		if os.Getuid() == 0 {
			t.Error("the plugin ran as uid 0 (this row must run as bitscan-runner)")
		}
		if err := RemoveTempDir(s.TempDir); err != nil {
			t.Fatal(err)
		}
		if _, err := os.Stat(s.TempDir); !os.IsNotExist(err) {
			t.Fatal("the temp dir is still there")
		}
	})
	t.Run("niceness 10 and I/O class idle (REQ-239 (3))", func(t *testing.T) {
		out, _, _, s := runPlugin(t, c, `echo NICE=$(awk '{print $19}' /proc/$$/stat); echo IO=$(ionice -p $$)`)
		_ = RemoveTempDir(s.TempDir)
		if field(out, "NICE") != "10" || !strings.HasPrefix(field(out, "IO"), "idle") {
			t.Fatalf("NICE %q IO %q", field(out, "NICE"), field(out, "IO"))
		}
		// CHK-M10-128 part 2: after 20 spawns (from concurrent goroutines,
		// so the start goroutines land on many threads), every thread of the
		// runner keeps niceness 0, m0 included.
		var wg sync.WaitGroup
		for range 4 {
			wg.Add(1)
			go func() {
				defer wg.Done()
				for range 5 {
					p, err := c.NewPlugin()
					if err != nil {
						t.Error(err)
						return
					}
					s, err := Spawn(p, "true", time.Now)
					if err != nil {
						t.Error(err)
						return
					}
					_, _ = io.Copy(io.Discard, s.Stdout)
					_, _ = s.Wait()
					_ = p.Kill()
					_ = p.WaitEmpty(t.Context())
					_ = p.Remove()
					_, _ = s.Stdout.Close(), s.Stderr.Close()
					_ = RemoveTempDir(s.TempDir)
				}
			}()
		}
		wg.Wait()
		time.Sleep(100 * time.Millisecond) // let the discarded start threads exit
		for _, b := range threadNiceness(t) {
			t.Errorf("runner %s, want niceness 0 and not I/O idle (CHK-M10-128)", b)
		}
	})
	t.Run("born in its own cgroup, with its first fork (REQ-238 (3))", func(t *testing.T) {
		out, _, _, s := runPlugin(t, c, `echo SELF=$(cut -d: -f3 /proc/$$/cgroup); sleep 30 & echo KID=$(cut -d: -f3 /proc/$!/cgroup); kill $!`)
		_ = RemoveTempDir(s.TempDir)
		self, kid := field(out, "SELF"), field(out, "KID")
		if !strings.Contains(self, "/p-") || self != kid || strings.HasSuffix(self, "/supervisor") {
			t.Fatalf("SELF %q KID %q", self, kid)
		}
	})
	t.Run("no Pdeathsig: a plugin outlives its start thread (#136 (c))", func(t *testing.T) {
		out, _, code, s := runPlugin(t, c, `sleep 2; echo done`)
		_ = RemoveTempDir(s.TempDir)
		if code != 0 || strings.TrimSpace(out) != "done" {
			t.Fatalf("exit %d out %q", code, out)
		}
	})
	t.Run("each plugin its own temp dir and cgroup", func(t *testing.T) {
		a, _, _, sa := runPlugin(t, c, `pwd; cut -d: -f3 /proc/$$/cgroup`)
		b, _, _, sb := runPlugin(t, c, `pwd; cut -d: -f3 /proc/$$/cgroup`)
		_, _ = RemoveTempDir(sa.TempDir), RemoveTempDir(sb.TempDir)
		if a == b {
			t.Fatalf("two plugins share %q", a)
		}
	})
	t.Run("a cgroup that can't be entered: no process (#136 (f))", func(t *testing.T) {
		p, err := c.NewPlugin()
		if err != nil {
			t.Fatal(err)
		}
		if err := p.Remove(); err != nil { // gone before the hop
			t.Fatal(err)
		}
		marker := filepath.Join(os.TempDir(), "spawn-should-not-run")
		s, err := Spawn(p, "touch "+marker, time.Now)
		if err == nil || s != nil {
			t.Fatalf("Spawn into a removed cgroup: s %v err %v", s, err)
		}
		time.Sleep(100 * time.Millisecond)
		if _, err := os.Stat(marker); err == nil {
			t.Fatal("a process ran without its cgroup")
		}
		ents, _ := filepath.Glob("/tmp/bitscan-p-*")
		t.Logf("RECORDED: temp dirs left after the failed spawn: %d (%v)", len(ents), err)
	})
}

// TASK-221 r1 (lead's row and reviewer-m10's): RemoveTempDir never changes
// anything outside the temp tree, and removes a tree a plugin locked (0000
// subdirectories). Runs as bitscan-runner: root would bypass the modes.
func TestDelegatedRemoveTempDir(t *testing.T) {
	if os.Getuid() == 0 {
		t.Fatal("must run as bitscan-runner: root bypasses the modes")
	}
	base := t.TempDir()
	outside := filepath.Join(base, "outside")
	if err := os.Mkdir(outside, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(outside, "keep"), []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := unix.Chmod(outside, 0o500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = unix.Chmod(outside, 0o700) })
	mode := func() os.FileMode { fi, _ := os.Stat(outside); return fi.Mode().Perm() }
	t.Run("static: a locked subdir and a symlinked subdir", func(t *testing.T) {
		dir := filepath.Join(base, "bitscan-p-static")
		for _, d := range []string{"locked/deep", "sub"} {
			if err := os.MkdirAll(filepath.Join(dir, d), 0o700); err != nil {
				t.Fatal(err)
			}
		}
		_ = os.WriteFile(filepath.Join(dir, "locked", "deep", "f"), []byte("x"), 0o600)
		_ = unix.Chmod(filepath.Join(dir, "locked", "deep"), 0)
		_ = unix.Chmod(filepath.Join(dir, "locked"), 0)
		_ = os.Remove(filepath.Join(dir, "sub"))
		if err := os.Symlink(outside, filepath.Join(dir, "sub")); err != nil {
			t.Fatal(err)
		}
		if err := RemoveTempDir(dir); err != nil {
			t.Fatalf("RemoveTempDir: %v", err)
		}
		if _, err := os.Lstat(dir); !os.IsNotExist(err) {
			t.Fatal("the temp tree is still there")
		}
		if m := mode(); m != 0o500 {
			t.Fatalf("outside dir mode %o, want 500", m)
		}
		if _, err := os.Stat(filepath.Join(outside, "keep")); err != nil {
			t.Fatal("a file outside was removed")
		}
	})
	t.Run("race: a parallel plugin swaps a subdir for a symlink", func(t *testing.T) {
		const rounds = 1000
		for i := range rounds {
			dir := filepath.Join(base, fmt.Sprintf("bitscan-p-race-%d", i))
			x := filepath.Join(dir, "x")
			if err := os.MkdirAll(filepath.Join(x, "y"), 0o700); err != nil {
				t.Fatal(err)
			}
			_ = os.WriteFile(filepath.Join(x, "y", "f"), []byte("x"), 0o600)
			_ = unix.Chmod(filepath.Join(x, "y"), 0)
			_ = unix.Chmod(x, 0)
			stop := make(chan struct{})
			done := make(chan struct{})
			go func() { // the "parallel plugin": swaps x for a symlink and back
				defer close(done)
				for {
					select {
					case <-stop:
						return
					default:
					}
					if os.Rename(x, x+".real") == nil {
						_ = os.Symlink(outside, x)
						_ = os.Remove(x)
						_ = os.Rename(x+".real", x)
					}
				}
			}()
			_ = RemoveTempDir(dir)
			close(stop)
			<-done
			if m := mode(); m != 0o500 {
				t.Fatalf("round %d: outside dir mode %o: a chmod left the temp tree", i, m)
			}
			for _, d := range []string{x + ".real", x, filepath.Join(x+".real", "y"), filepath.Join(x, "y")} {
				_ = unix.Chmod(d, 0o700)
			}
			_ = os.RemoveAll(dir)
		}
	})
}
