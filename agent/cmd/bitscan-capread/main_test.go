//go:build linux

// CHK-M10-177 (tester-m10c): the built `bitscan-capread` binary, REQ-253 (2),
// REQ-252, #142 (g): any argument list other than one known name exits 2
// without connecting; `--serve` outside systemd refuses to start (exit 1, one
// line); with no helper enabled a known name is `not enabled`, exit 1.
package main

import (
	"bytes"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func build(t *testing.T) string {
	t.Helper()
	bin := filepath.Join(t.TempDir(), "bitscan-capread")
	cmd := exec.Command("go", "build", "-o", bin, ".") //nolint:gosec // the toolchain building this package
	cmd.Env = append(os.Environ(), "CGO_ENABLED=0")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("build: %v\n%s", err, out)
	}
	return bin
}

func runBin(t *testing.T, bin string, env []string, args ...string) (int, string, string) {
	t.Helper()
	cmd := exec.Command(bin, args...) //nolint:gosec // the binary just built, with the test's own argument lists
	cmd.Env = env
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	err := cmd.Run()
	var ee *exec.ExitError
	switch {
	case err == nil:
		return 0, out.String(), errb.String()
	case errors.As(err, &ee):
		return ee.ExitCode(), out.String(), errb.String()
	}
	t.Fatal(err)
	return -1, "", ""
}

func TestCapreadBinary(t *testing.T) {
	bin := build(t)
	env := []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin"}
	for _, args := range [][]string{nil, {""}, {"nft_ruleset", "extra"}, {"/bin/sh"}, {"audit_rules", "nft_ruleset"}, {"--serve", "x"}, {"NFT_RULESET"}} {
		code, out, errb := runBin(t, bin, env, args...)
		if code != 2 || out != "" || errb != "bitscan-capread: usage: bitscan-capread nft_ruleset|audit_rules\n" {
			t.Errorf("%q: exit %d stdout %q stderr %q, want 2 and the usage line", args, code, out, errb)
		}
	}
	for _, e := range [][]string{env, append(env, "LISTEN_PID=1", "LISTEN_FDS=1"), append(env, "LISTEN_FDS=1")} {
		code, out, errb := runBin(t, bin, e, "--serve")
		if code != 1 || out != "" || strings.Count(errb, "\n") != 1 {
			t.Errorf("--serve with %v: exit %d stdout %q stderr %q, want 1 and one line", e[1:], code, out, errb)
		}
	}
	if _, err := os.Stat("/run/bitscan/capread.sock"); errors.Is(err, os.ErrNotExist) {
		code, out, errb := runBin(t, bin, env, "nft_ruleset")
		if code != 1 || out != "" || errb != "bitscan-capread: not enabled\n" {
			t.Errorf("no helper: exit %d stdout %q stderr %q", code, out, errb)
		}
	} else {
		t.Log("RECORDED: /run/bitscan/capread.sock exists here; the not-enabled row is left to the client tests")
	}
}
