// TP-M10-19 import boundary (tester-m10c): REQ-251 (1), G75, CHK-M10-196,
// mutation rows CHK-M10-380 and -381; PD-41. For linux/amd64 builds (the
// only shipped target):
//   - bitscan-agent links internal/runner/proto and no other runner package,
//     no internal/redact, internal/capread or internal/sdsock, and not
//     golang.org/x/sys (PD-41: runner, sdsock and capread only);
//   - bitscan-runner and bitscan-capread link no HTTP, TLS or agent
//     transport code (they never talk to the manager).
//
// A test-only package: it runs `go list -deps` for the three commands.
package internal_test

import (
	"os"
	"os/exec"
	"strings"
	"testing"
)

func deps(t *testing.T, pkg string) map[string]bool {
	t.Helper()
	cmd := exec.Command("go", "list", "-deps", "-f", "{{.ImportPath}}", pkg) //nolint:gosec // the toolchain listing a fixed package
	cmd.Dir = ".."
	cmd.Env = append(os.Environ(), "GOOS=linux", "GOARCH=amd64", "CGO_ENABLED=0")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("go list -deps %s: %v\n%s", pkg, err, out)
	}
	m := map[string]bool{}
	for _, l := range strings.Fields(string(out)) {
		m[l] = true
	}
	if len(m) < 10 {
		t.Fatalf("go list -deps %s listed only %d packages: the walk is wrong", pkg, len(m))
	}
	return m
}

func TestImportBoundary(t *testing.T) {
	const mod = "bitscan.local/agent/"
	agent := deps(t, "./cmd/bitscan-agent")
	if !agent[mod+"internal/runner/proto"] || !agent[mod+"internal/agent/runnerclient"] || !agent[mod+"internal/spool"] {
		t.Error("bitscan-agent does not link proto, runnerclient and spool: the walk is wrong")
	}
	for p := range agent {
		switch {
		case strings.HasPrefix(p, mod+"internal/runner") && p != mod+"internal/runner/proto":
			t.Errorf("bitscan-agent links %s (REQ-251 (1), CHK-M10-380)", p)
		case p == mod+"internal/redact", p == mod+"internal/capread", p == mod+"internal/sdsock":
			t.Errorf("bitscan-agent links %s (REQ-251 (1), CHK-M10-380)", p)
		case strings.HasPrefix(p, "golang.org/x/sys"):
			t.Errorf("bitscan-agent links %s (PD-41)", p)
		}
	}
	for _, cmd := range []string{"./cmd/bitscan-runner", "./cmd/bitscan-capread"} {
		d := deps(t, cmd)
		for _, bad := range []string{"net/http", "crypto/tls", mod + "internal/agent/transport", mod + "internal/agent/enrol", mod + "internal/agent/loops"} {
			if d[bad] {
				t.Errorf("%s links %s (CHK-M10-381)", cmd, bad)
			}
		}
		for p := range d {
			if strings.HasPrefix(p, "net/http") {
				t.Errorf("%s links %s (CHK-M10-381)", cmd, p)
			}
		}
	}
	if d := deps(t, "./cmd/bitscan-runner"); !d[mod+"internal/runner"] || !d["golang.org/x/sys/unix"] {
		t.Error("bitscan-runner does not link internal/runner and x/sys/unix: the walk is wrong")
	}
}
