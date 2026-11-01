// TP-M10-09 (tester-m10): runner hygiene and start-up refusals, REQ-237;
// #137. Expected values from REQ-237 (1) and #137.
package runner

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"testing"

	"golang.org/x/sys/unix"
)

const okStatus = "Name:\tbitscan-runner\nCapInh:\t0000000000000000\nCapPrm:\t0000000000000004\nCapEff:\t0000000000000004\nCapBnd:\t0000000000000004\nCapAmb:\t0000000000000004\n"

func okProbe() StartupProbe {
	return StartupProbe{
		Euid:         func() int { return 998 },
		Status:       func() ([]byte, error) { return []byte(okStatus), nil },
		StatfsCgroup: func() (int64, error) { return unix.CGROUP2_SUPER_MAGIC, nil },
		SelfCgroup:   func() ([]byte, error) { return []byte("0::/system.slice/bitscan-runner.service\n"), nil },
	}
}

func withStatus(eff, bnd string) func() ([]byte, error) {
	s := strings.Replace(okStatus, "CapEff:\t0000000000000004", "CapEff:\t"+eff, 1)
	s = strings.Replace(s, "CapBnd:\t0000000000000004", "CapBnd:\t"+bnd, 1)
	return func() ([]byte, error) { return []byte(s), nil }
}

// CHK-M10-110, -112: REQ-237 (1) each failing input refuses with its own
// line; the passing set starts.
func TestCheckStartup(t *testing.T) {
	if err := CheckStartup(okProbe()); err != nil {
		t.Fatalf("the passing set refused: %v", err)
	}
	p := okProbe()
	p.Status = withStatus("0000000000000000", "0000000000000004")
	if err := CheckStartup(p); err != nil {
		t.Fatalf("CapEff 0 (a subset) refused: %v", err)
	}
	type tc struct {
		name string
		mod  func(*StartupProbe)
		word string
	}
	cases := []tc{
		{"euid 0", func(p *StartupProbe) { p.Euid = func() int { return 0 } }, "effective uid is 0"},
		{"CapBnd full", func(p *StartupProbe) { p.Status = withStatus("0000000000000004", "000001ffffffffff") }, "CapBnd"},
		{"CapEff + CAP_SYS_ADMIN", func(p *StartupProbe) { p.Status = withStatus("0000000000200004", "0000000000200004") }, "CapEff"},
		{"CapEff CAP_NET_ADMIN only", func(p *StartupProbe) { p.Status = withStatus("0000000000001000", "0000000000000004") }, "CapEff"},
		{"CapBnd + CAP_DAC_OVERRIDE", func(p *StartupProbe) { p.Status = withStatus("0000000000000004", "0000000000000006") }, "CapBnd"},
		{"no CapEff line", func(p *StartupProbe) {
			p.Status = func() ([]byte, error) { return []byte("CapBnd:\t0000000000000004\n"), nil }
		}, "CapEff"},
		{"two CapEff lines", func(p *StartupProbe) {
			p.Status = func() ([]byte, error) { return []byte(okStatus + "CapEff:\t0000000000000004\n"), nil }
		}, "CapEff"},
		{"CapEff not hex", func(p *StartupProbe) { p.Status = withStatus("zz", "0000000000000004") }, "CapEff"},
		{"status unreadable", func(p *StartupProbe) { p.Status = func() ([]byte, error) { return nil, errors.New("x") } }, "/proc/self/status"},
		{"tmpfs at /sys/fs/cgroup", func(p *StartupProbe) { p.StatfsCgroup = func() (int64, error) { return 0x01021994, nil } }, "not cgroup2"},
		{"cgroup v1 (tmpfs + cgroup) magic", func(p *StartupProbe) { p.StatfsCgroup = func() (int64, error) { return 0x27e0eb, nil } }, "not cgroup2"},
		{"statfs error", func(p *StartupProbe) { p.StatfsCgroup = func() (int64, error) { return 0, errors.New("x") } }, "not cgroup2"},
		{"hybrid /proc/self/cgroup", func(p *StartupProbe) {
			p.SelfCgroup = func() ([]byte, error) { return []byte("1:name=systemd:/x\n0::/x\n"), nil }
		}, "unified"},
		{"v1 /proc/self/cgroup", func(p *StartupProbe) {
			p.SelfCgroup = func() ([]byte, error) { return []byte("12:memory:/x\n"), nil }
		}, "unified"},
		{"self cgroup unreadable", func(p *StartupProbe) { p.SelfCgroup = func() ([]byte, error) { return nil, errors.New("x") } }, "/proc/self/cgroup"},
	}
	seen := map[string]bool{}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			p := okProbe()
			c.mod(&p)
			err := CheckStartup(p)
			if err == nil {
				t.Fatal("started")
			}
			msg := err.Error()
			if !strings.Contains(msg, c.word) || strings.Contains(msg, "\n") {
				t.Fatalf("message %q (want one line naming %q)", msg, c.word)
			}
			seen[msg] = true
		})
	}
	if len(seen) < 6 {
		t.Fatalf("only %d distinct refusal lines", len(seen))
	}
	// The order: euid is checked before capabilities (a root runner never
	// gets as far as the cgroup checks).
	p = okProbe()
	p.Euid = func() int { return 0 }
	p.Status = withStatus("000001ffffffffff", "000001ffffffffff")
	if err := CheckStartup(p); err == nil || !strings.Contains(err.Error(), "uid") {
		t.Fatalf("root with all caps: %v", err)
	}
}

// The real probe on this host gives sane values (recorded: this host runs
// the test as root, so CheckStartup must refuse with the euid line).
func TestSystemProbeLinux(t *testing.T) {
	err := CheckStartup(SystemProbe())
	t.Logf("RECORDED: CheckStartup on this host (euid %d): %v", os.Geteuid(), err)
	if os.Geteuid() == 0 && (err == nil || !strings.Contains(err.Error(), "uid is 0")) {
		t.Fatalf("root not refused: %v", err)
	}
	var st unix.Statfs_t
	if unix.Statfs("/sys/fs/cgroup", &st) == nil && st.Type == unix.CGROUP2_SUPER_MAGIC {
		p := SystemProbe()
		p.Euid = func() int { return 1000 }
		p.Status = func() ([]byte, error) { return []byte(okStatus), nil }
		if err := CheckStartup(p); err != nil {
			t.Fatalf("this cgroup2 host refused with good caps: %v", err)
		}
	}
}

// CHK-M10-111: PR_GET_DUMPABLE is 0 after Harden (in a child process, so
// the test binary itself stays dumpable).
func TestHardenLinux(t *testing.T) {
	if os.Getenv("M10_HARDEN_CHILD") == "1" {
		if err := Harden(); err != nil {
			fmt.Println("HARDEN-ERR", err)
			os.Exit(3)
		}
		v, _ := unix.PrctlRetInt(unix.PR_GET_DUMPABLE, 0, 0, 0, 0)
		b, _ := os.ReadFile("/proc/self/status")
		fmt.Printf("DUMPABLE %d\n", v)
		_ = b
		os.Exit(0)
	}
	cmd := exec.Command(os.Args[0], "-test.run", "^TestHardenLinux$") //nolint:gosec // the test binary itself
	cmd.Env = append(os.Environ(), "M10_HARDEN_CHILD=1")
	out, err := cmd.CombinedOutput()
	if err != nil || !strings.Contains(string(out), "DUMPABLE 0") {
		t.Fatalf("child: %v %q", err, out)
	}
	if v, _ := unix.PrctlRetInt(unix.PR_GET_DUMPABLE, 0, 0, 0, 0); v != 1 {
		t.Fatalf("the parent test process changed: dumpable %d", v)
	}
}
