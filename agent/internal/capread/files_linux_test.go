// The capread helper's fixed-file request (TS §3.7: "reading
// /sys/kernel/security/apparmor/profiles"; owner decision 2026-11-13). Internal
// test (package capread): the file table is swapped for test files.
package capread

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// withFiles swaps the file table for the test.
func withFiles(t *testing.T, table map[string]string) {
	t.Helper()
	old := files
	files = table
	t.Cleanup(func() { files = old })
}

func TestRealFileTableIsTheSpecs(t *testing.T) {
	if len(files) != 1 || files["apparmor_profiles"] != "/sys/kernel/security/apparmor/profiles" {
		t.Fatalf("file table %q", files)
	}
	if !Known("apparmor_profiles") || Known("APPARMOR_PROFILES") || Known("apparmor") {
		t.Fatal("Known does not match the file table exactly")
	}
	if _, clash := commands["apparmor_profiles"]; clash {
		t.Fatal("a name is in both tables")
	}
}

func TestFileRequestAnswersTheFixedFile(t *testing.T) {
	f := filepath.Join(t.TempDir(), "profiles")
	if err := os.WriteFile(f, []byte("docker-default (enforce)\nman_filter (complain)\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	withFiles(t, map[string]string{"apparmor_profiles": f})
	path, logs := serveTest(t)
	if got := ask(t, path, "apparmor_profiles\n"); got != "ok\ndocker-default (enforce)\nman_filter (complain)\n" {
		t.Fatalf("answer %q", got)
	}
	if !strings.Contains(logs.String(), "request=apparmor_profiles") || !strings.Contains(logs.String(), "result=ok") {
		t.Fatalf("log %q", logs)
	}
	if strings.Contains(logs.String(), "docker-default") {
		t.Fatal("file content in the log")
	}
}

func TestFileRequestTakesNoPath(t *testing.T) {
	f := filepath.Join(t.TempDir(), "profiles")
	if err := os.WriteFile(f, []byte("x\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	withFiles(t, map[string]string{"apparmor_profiles": f})
	path, _ := serveTest(t)
	for _, req := range []string{
		"apparmor_profiles /etc/shadow\n",
		"apparmor_profiles\n/etc/shadow\n",
		"/etc/shadow\n",
		"apparmor_profiles",
	} {
		if got := ask(t, path, req); got != "error unknown_request\n" {
			t.Fatalf("%q answered %q", req, got)
		}
	}
}

func TestFileRequestErrors(t *testing.T) {
	dir := t.TempDir()
	missing := filepath.Join(dir, "missing")
	atCap := filepath.Join(dir, "at-cap")
	overCap := filepath.Join(dir, "over-cap")
	if err := os.WriteFile(atCap, []byte(strings.Repeat("a", maxOutput)), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(overCap, []byte(strings.Repeat("a", maxOutput+1)), 0o600); err != nil {
		t.Fatal(err)
	}
	cases := []struct{ file, want string }{
		{missing, "error not_installed\n"},
		{overCap, "error too_large\n"},
	}
	for _, c := range cases {
		withFiles(t, map[string]string{"apparmor_profiles": c.file})
		path, _ := serveTest(t)
		if got := ask(t, path, "apparmor_profiles\n"); got != c.want {
			t.Fatalf("%s answered %q, want %q", filepath.Base(c.file), got, c.want)
		}
	}
	withFiles(t, map[string]string{"apparmor_profiles": atCap})
	path, _ := serveTest(t)
	if got := ask(t, path, "apparmor_profiles\n"); len(got) != len("ok\n")+maxOutput {
		t.Fatalf("a file of exactly the cap answered %d bytes", len(got))
	}
}

// A file the helper may not open answers "failed 1", as cat would exit.
// Root reads any mode-000 file, so this row runs as a normal user only.
func TestFileRequestUnreadable(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("named skip: root can open a mode-000 file; this row runs in the non-root go test step")
	}
	f := filepath.Join(t.TempDir(), "locked")
	if err := os.WriteFile(f, []byte("secret\n"), 0o000); err != nil {
		t.Fatal(err)
	}
	withFiles(t, map[string]string{"apparmor_profiles": f})
	path, _ := serveTest(t)
	if got := ask(t, path, "apparmor_profiles\n"); got != "error failed 1\n" {
		t.Fatalf("answer %q", got)
	}
}
