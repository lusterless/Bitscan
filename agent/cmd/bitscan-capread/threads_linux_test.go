//go:build linux

package main

import (
	"bufio"
	"bytes"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// childSocket is set only by TestClientThreads on the copy of this test binary
// it starts; production never reads it.
const childSocket = "BITSCAN_CAPREAD_TEST_CHILD_SOCKET"

// TestMain lets the test binary act as the client: with childSocket set it
// runs client() exactly as main() does, then prints its own thread count to
// fd 3. The Go runtime does not end idle OS threads, so the count at exit is
// the peak.
func TestMain(m *testing.M) {
	if sock := os.Getenv(childSocket); sock != "" {
		code := client(os.Args[1:], sock)
		report := os.NewFile(3, "report")
		_, _ = fmt.Fprintf(report, "%d %d\n", code, threads())
		os.Exit(code)
	}
	os.Exit(m.Run())
}

func threads() int {
	b, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return -1
	}
	sc := bufio.NewScanner(bytes.NewReader(b))
	for sc.Scan() {
		if v, ok := strings.CutPrefix(sc.Text(), "Threads:"); ok {
			n, _ := strconv.Atoi(strings.TrimSpace(v))
			return n
		}
	}
	return -1
}

// fakeHelper answers each connection like the real helper: one request line,
// then "ok" and the answer in chunks with pauses, so the client waits in the
// network poller many times, as it does on a slow or busy host.
func fakeHelper(t *testing.T, answer []byte, chunks int, pause time.Duration) string {
	t.Helper()
	sock := filepath.Join(t.TempDir(), "capread.sock")
	l, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = l.Close() })
	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			go func() {
				defer func() { _ = c.Close() }()
				if _, err := bufio.NewReader(c).ReadString('\n'); err != nil {
					return
				}
				if _, err := c.Write([]byte("ok\n")); err != nil {
					return
				}
				step := max(1, len(answer)/chunks)
				for off := 0; off < len(answer); off += step {
					time.Sleep(pause)
					if _, err := c.Write(answer[off:min(off+step, len(answer))]); err != nil {
						return
					}
				}
			}()
		}
	}()
	return sock
}

// maxClientThreads bounds the client's OS threads. With one P the runtime
// needs the main thread, sysmon, at most one thread spinning for work or
// running the GC worker, and one that takes the P over while another blocks
// in a system call (the write to the plugin's stdout pipe), plus one spare
// for the template thread. The runner's cgroup allows 64 tasks in all, and
// the runner itself uses about 10.
const maxClientThreads = 6

// TestClientThreads runs the real client path with the GOMAXPROCS it starts
// with and checks it stays at a few threads.
//
// GOMAXPROCS in the environment stands in for the CPU count: the runtime
// takes it before anything else. From about 250 Ps the runtime's own per-P
// heap passes the 4 MB minimum and a garbage collection with GOMAXPROCS/4
// dedicated mark workers runs before main(), which no code in the client can
// prevent. Large hosts are therefore covered by the runner: it copies its own
// cpu.max (CPUQuota=25%) into each plugin cgroup, so the client starts with
// GOMAXPROCS=2 whatever the CPU count (the "behind the runner's limit" rows
// here, and the delegated runner row that checks the limit and the
// GOMAXPROCS a Go program gets in a plugin cgroup). The other rows cover
// hosts where no cgroup limit applies, up to the largest count without a
// collection before main() in this test binary (it allocates more at start-up than the client; 192 here, about 250 for the client): there the client's own runtime.GOMAXPROCS(1)
// keeps the collection that reading a large answer triggers on one P.
func TestClientThreads(t *testing.T) {
	if testing.Short() {
		t.Skip("starts the client many times")
	}
	answer := bytes.Repeat([]byte("/usr/bin/example-profile (enforce)\n"), 29000) // 1,015,000 bytes, just under the 1 MiB cap
	cases := []struct {
		name   string
		procs  int // GOMAXPROCS the client starts with
		chunks int
		pause  time.Duration
		runs   int
	}{
		{"256 CPUs behind the runner's limit", 2, 200, time.Millisecond, 5},
		{"256 CPUs behind the runner's limit, one burst", 2, 1, 0, 5},
		{"4 CPUs", 4, 200, time.Millisecond, 5},
		{"64 CPUs", 64, 200, time.Millisecond, 5},
		{"64 CPUs, one burst", 64, 1, 0, 5},
		{"192 CPUs", 192, 200, time.Millisecond, 5},
		{"192 CPUs, one burst", 192, 1, 0, 5},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			sock := fakeHelper(t, answer, tc.chunks, tc.pause)
			peak := 0
			for range tc.runs {
				r, w, err := os.Pipe()
				if err != nil {
					t.Fatal(err)
				}
				cmd := exec.Command(os.Args[0], "apparmor_profiles") //nolint:gosec // this test binary, re-run as the client
				// Only PATH, as the runner gives plugins (TS §3.5), plus the
				// test's socket and the CPU count to imitate.
				cmd.Env = []string{
					"PATH=/usr/sbin:/usr/bin:/sbin:/bin",
					childSocket + "=" + sock,
					"GOMAXPROCS=" + strconv.Itoa(tc.procs),
				}
				var out bytes.Buffer
				cmd.Stdout = &out
				cmd.ExtraFiles = []*os.File{w}
				err = cmd.Run()
				_ = w.Close()
				rep, _ := bufio.NewReader(r).ReadString('\n')
				_ = r.Close()
				var code, n int
				if _, serr := fmt.Sscanf(rep, "%d %d", &code, &n); serr != nil {
					t.Fatalf("client: %v, no thread report %q", err, rep)
				}
				if code != 0 || !bytes.Equal(out.Bytes(), answer) {
					t.Fatalf("client exit %d with %d bytes, want 0 and the whole answer", code, out.Len())
				}
				peak = max(peak, n)
			}
			t.Logf("GOMAXPROCS=%d: peak %d threads over %d runs", tc.procs, peak, tc.runs)
			if peak > maxClientThreads {
				t.Errorf("GOMAXPROCS=%d: the client reached %d threads, want at most %d", tc.procs, peak, maxClientThreads)
			}
		})
	}
}
