package runner

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"

	"golang.org/x/sys/unix"
)

// capDacReadSearch is the only capability the runner may hold (TS §3.7
// L276; the unit's AmbientCapabilities= and CapabilityBoundingSet=).
const capDacReadSearch = 1 << unix.CAP_DAC_READ_SEARCH

// Harden is the first call in main: it makes the runner non-dumpable, so a
// plugin running as the same user cannot read its memory or attach to it
// (TS §3.7 L283), and checks that it took effect.
func Harden() error {
	if err := unix.Prctl(unix.PR_SET_DUMPABLE, 0, 0, 0, 0); err != nil {
		return fmt.Errorf("runner: PR_SET_DUMPABLE: %w", err)
	}
	if v, err := unix.PrctlRetInt(unix.PR_GET_DUMPABLE, 0, 0, 0, 0); err != nil || v != 0 {
		return errors.New("runner: still dumpable after PR_SET_DUMPABLE 0")
	}
	return nil
}

// StartupProbe holds the readers CheckStartup uses, injectable for tests.
type StartupProbe struct {
	Euid         func() int
	Status       func() ([]byte, error) // /proc/self/status
	StatfsCgroup func() (int64, error)  // statfs("/sys/fs/cgroup").Type
	SelfCgroup   func() ([]byte, error) // /proc/self/cgroup
}

// SystemProbe reads the running process and host.
func SystemProbe() StartupProbe {
	return StartupProbe{
		Euid:   os.Geteuid,
		Status: func() ([]byte, error) { return os.ReadFile("/proc/self/status") },
		StatfsCgroup: func() (int64, error) {
			var st unix.Statfs_t
			if err := unix.Statfs(cgroupMount, &st); err != nil {
				return 0, fmt.Errorf("runner: statfs %s: %w", cgroupMount, err)
			}
			return st.Type, nil
		},
		SelfCgroup: readSelfCgroup,
	}
}

// CheckStartup refuses to start (#137) when the runner is root, holds any
// capability beyond CAP_DAC_READ_SEARCH in its effective or bounding set,
// or the host is not on the unified cgroup v2 hierarchy (TS §3 L152). The
// error names the failed check and nothing else. The delegation checks are
// Cgroups.Setup's and the socket checks are sdsock's.
func CheckStartup(p StartupProbe) error {
	if p.Euid() == 0 {
		return errors.New("runner: refusing to start: effective uid is 0")
	}
	status, err := p.Status()
	if err != nil {
		return errors.New("runner: refusing to start: cannot read /proc/self/status")
	}
	for _, key := range []string{"CapEff", "CapBnd"} {
		set, ok := capSet(status, key)
		if !ok {
			return fmt.Errorf("runner: refusing to start: no readable %s line", key)
		}
		if set&^capDacReadSearch != 0 {
			return fmt.Errorf("runner: refusing to start: %s holds capabilities beyond CAP_DAC_READ_SEARCH", key)
		}
	}
	if magic, err := p.StatfsCgroup(); err != nil || magic != unix.CGROUP2_SUPER_MAGIC {
		return errors.New("runner: refusing to start: /sys/fs/cgroup is not cgroup2")
	}
	b, err := p.SelfCgroup()
	if err != nil {
		return errors.New("runner: refusing to start: cannot read /proc/self/cgroup")
	}
	if _, err := parseSelfCgroup(b); err != nil {
		return errors.New("runner: refusing to start: not on the unified cgroup v2 hierarchy")
	}
	return nil
}

// capSet parses the one "<key>:\t<hex>" line of /proc/self/status. A
// missing, repeated or unparsable line is not ok.
func capSet(status []byte, key string) (uint64, bool) {
	var val string
	n := 0
	for _, line := range strings.Split(string(status), "\n") {
		if v, ok := strings.CutPrefix(line, key+":"); ok {
			val, n = strings.TrimSpace(v), n+1
		}
	}
	set, err := strconv.ParseUint(val, 16, 64)
	return set, n == 1 && err == nil
}
