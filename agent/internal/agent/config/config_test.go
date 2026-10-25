// Tests for the agent.yaml loader (TS §3.6, #4 as made concrete in the M4
// re-check, lead rulings 2026-10-24; tests/m4/test-plan.md TP-M4-02,
// CHK-M4-020 to -025, mutation rows CHK-M4-320, -342, -343).
package config_test

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/config"
)

const goodURL = "manager_url: https://mgr.example:8443\n"

// specExample returns the TS §3.6 agent.yaml block, read from the spec file.
func specExample(t *testing.T) []byte {
	t.Helper()
	spec, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "docs", "spec", "Technical_Specification.md"))
	if err != nil {
		t.Fatalf("spec not readable: %v", err)
	}
	text := strings.ReplaceAll(string(spec), "\r\n", "\n")
	_, after, ok := strings.Cut(text, "### 3.6 Agent configuration (`agent.yaml`)\n")
	if !ok {
		t.Fatal("TS §3.6 heading not found")
	}
	_, block, ok := strings.Cut(after, "```yaml\n")
	if !ok {
		t.Fatal("TS §3.6 yaml fence not found")
	}
	block, _, ok = strings.Cut(block, "```")
	if !ok {
		t.Fatal("TS §3.6 closing fence not found")
	}
	if n := strings.Count(block, "\n"); n != 9 {
		t.Fatalf("TS §3.6 block has %d lines, want 9 (L258-L266)", n)
	}
	return []byte(block)
}

// CHK-M4-020: the spec example loads with exactly its values.
func TestSpecExampleLoadsExactly(t *testing.T) {
	c, err := config.Parse(specExample(t))
	if err != nil {
		t.Fatalf("TS §3.6 example refused: %v", err)
	}
	want := config.Config{
		ManagerURL:         "https://mgr.example:8443",
		CAFile:             "",
		ManagerSPKISHA256:  "",
		StateDir:           "/var/lib/bitscan-agent",
		HeartbeatSeconds:   300,
		JobPullSeconds:     300,
		MaxParallelPlugins: 2,
		SpoolMaxMB:         50,
		LogLevel:           "info",
	}
	if c != want {
		t.Fatalf("loaded %+v\nwant   %+v", c, want)
	}
	if config.Path != "/etc/bitscan/agent.yaml" || config.StateDir != "/var/lib/bitscan-agent" || config.HeartbeatSeconds != 300 {
		t.Fatalf("constants %q %q %d", config.Path, config.StateDir, config.HeartbeatSeconds)
	}
}

// Only manager_url is required; every other key has the TS §3.6 default.
func TestDefaultsWithOnlyTheURL(t *testing.T) {
	c, err := config.Parse([]byte(goodURL))
	if err != nil {
		t.Fatal(err)
	}
	if c.JobPullSeconds != 300 || c.MaxParallelPlugins != 2 || c.SpoolMaxMB != 50 || c.LogLevel != "info" ||
		c.StateDir != "/var/lib/bitscan-agent" || c.HeartbeatSeconds != 300 || c.CAFile != "" || c.ManagerSPKISHA256 != "" {
		t.Fatalf("defaults %+v", c)
	}
}

func assertRefused(t *testing.T, doc string, key string) {
	t.Helper()
	_, err := config.Parse([]byte(doc))
	if err == nil {
		t.Fatalf("accepted:\n%s", doc)
	}
	msg := err.Error()
	if strings.Contains(msg, "\n") {
		t.Errorf("error is not one line: %q", msg)
	}
	if !strings.HasPrefix(msg, "agent.yaml: ") {
		t.Errorf("error %q does not start with the file name", msg)
	}
	if key != "" && !strings.Contains(msg, key) {
		t.Errorf("error %q does not name %q", msg, key)
	}
	if strings.Contains(msg, "CANARY") {
		t.Errorf("error echoes a value: %q", msg)
	}
}

// CHK-M4-021: each refusal names its key in one line and echoes no value.
func TestRefusals(t *testing.T) {
	cases := map[string]struct{ doc, key string }{
		// manager_url (CHK-M4-320)
		"http URL":           {"manager_url: http://CANARY.example:8443\n", "manager_url"},
		"HTTP URL uppercase": {"manager_url: HTTP://CANARY.example\n", "manager_url"},
		"ftp URL":            {"manager_url: ftp://CANARY.example\n", "manager_url"},
		"scheme-relative":    {"manager_url: //CANARY.example:8443\n", "manager_url"},
		"no scheme":          {"manager_url: CANARY.example:8443\n", "manager_url"},
		"https no host":      {"manager_url: https://\n", "manager_url"},
		"https port only":    {"manager_url: https://:8443\n", "manager_url"},
		"https opaque":       {"manager_url: https:CANARY.example\n", "manager_url"},
		"empty URL":          {"manager_url: \"\"\n", "manager_url"},
		"null URL":           {"manager_url: ~\n", "manager_url"},
		"missing URL":        {"job_pull_seconds: 300\n", "manager_url"},
		"URL as list":        {"manager_url: [https://CANARY.example]\n", "manager_url"},
		"URL with space":     {"manager_url: \"https://CANARY.example \"\n", "manager_url"},
		// pin (#79)
		"pin 63 hex":      {goodURL + "manager_spki_sha256: " + strings.Repeat("a", 63) + "\n", "manager_spki_sha256"},
		"pin 65 hex":      {goodURL + "manager_spki_sha256: " + strings.Repeat("a", 65) + "\n", "manager_spki_sha256"},
		"pin non hex":     {goodURL + "manager_spki_sha256: " + strings.Repeat("g", 64) + "\n", "manager_spki_sha256"},
		"pin base64":      {goodURL + "manager_spki_sha256: CANARYb64AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n", "manager_spki_sha256"},
		"pin with colons": {goodURL + "manager_spki_sha256: " + strings.TrimSuffix(strings.Repeat("ab:", 32), ":") + "\n", "manager_spki_sha256"},
		// fixed keys (#4)
		"state_dir other": {goodURL + "state_dir: /tmp/CANARY\n", "state_dir"},
		"state_dir slash": {goodURL + "state_dir: /var/lib/bitscan-agent/\n", "state_dir"},
		"heartbeat 299":   {goodURL + "heartbeat_seconds: 299\n", "heartbeat_seconds"},
		"heartbeat 301":   {goodURL + "heartbeat_seconds: 301\n", "heartbeat_seconds"},
		"heartbeat 60":    {goodURL + "heartbeat_seconds: 60\n", "heartbeat_seconds"},
		// ranges
		"pull 59":       {goodURL + "job_pull_seconds: 59\n", "job_pull_seconds"},
		"pull 3601":     {goodURL + "job_pull_seconds: 3601\n", "job_pull_seconds"},
		"pull 0":        {goodURL + "job_pull_seconds: 0\n", "job_pull_seconds"},
		"pull -300":     {goodURL + "job_pull_seconds: -300\n", "job_pull_seconds"},
		"pull string":   {goodURL + "job_pull_seconds: \"300\"\n", "job_pull_seconds"},
		"pull float":    {goodURL + "job_pull_seconds: 300.5\n", "job_pull_seconds"},
		"pull 300.0":    {goodURL + "job_pull_seconds: 300.0\n", "job_pull_seconds"},
		"pull exponent": {goodURL + "job_pull_seconds: 3e2\n", "job_pull_seconds"},
		"pull bool":     {goodURL + "job_pull_seconds: true\n", "job_pull_seconds"},
		"pull huge":     {goodURL + "job_pull_seconds: 99999999999999999999999\n", "job_pull_seconds"},
		"pull null":     {goodURL + "job_pull_seconds: ~\n", "job_pull_seconds"},
		"parallel 0":    {goodURL + "max_parallel_plugins: 0\n", "max_parallel_plugins"},
		"parallel 9":    {goodURL + "max_parallel_plugins: 9\n", "max_parallel_plugins"},
		"spool 0":       {goodURL + "spool_max_mb: 0\n", "spool_max_mb"},
		"spool 51":      {goodURL + "spool_max_mb: 51\n", "spool_max_mb"},
		"log trace":     {goodURL + "log_level: trace\n", "log_level"},
		"log INFO":      {goodURL + "log_level: INFO\n", "log_level"},
		"log Info":      {goodURL + "log_level: Info\n", "log_level"},
		"log warning":   {goodURL + "log_level: warning\n", "log_level"},
		"log empty":     {goodURL + "log_level: \"\"\n", "log_level"},
		// unknown keys (CHK-M4-343)
		"inventory false":   {goodURL + "inventory: false\n", "inventory"},
		"inventory_enabled": {goodURL + "inventory_enabled: false\n", "inventory_enabled"},
		"key case":          {goodURL + "Manager_url: https://x.example\n", "Manager_url"},
		"nested map":        {goodURL + "proxy:\n  url: http://CANARY\n", "proxy"},
		"nested value":      {goodURL + "log_level:\n  level: info\n", "log_level"},
		"merge key":         {"base: &b\n  job_pull_seconds: 60\n" + goodURL + "<<: *b\n", ""},
		"unprintable key":   {goodURL + "\"CANARY\\u00e9\": 1\n", ""},
		// structure
		"duplicate key":    {goodURL + goodURL, "manager_url"},
		"duplicate pull":   {goodURL + "job_pull_seconds: 60\njob_pull_seconds: 120\n", "job_pull_seconds"},
		"two documents":    {goodURL + "---\n" + goodURL, ""},
		"top-level list":   {"- manager_url: https://x.example\n", ""},
		"top-level scalar": {"https://x.example\n", ""},
		"empty file":       {"", "manager_url"},
		"only comments":    {"# nothing\n", "manager_url"},
		"alias value":      {"x: &u https://x.example\nmanager_url: *u\n", ""},
		"malformed tab":    {"manager_url: https://x.example\n\tjob_pull_seconds: 60\n", ""},
		"unclosed quote":   {"manager_url: \"https://CANARY.example\n", ""},
		"unclosed flow":    {"manager_url: [https://CANARY.example\n", ""},
		"bad escape":       {"manager_url: \"https://CANARY.example\\q\"\n", ""},
		"NUL byte":         {"manager_url: https://x.example\x00\n", ""},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) { assertRefused(t, c.doc, c.key) })
	}
}

// CHK-M4-022: boundaries and allowed forms are accepted.
func TestAccepted(t *testing.T) {
	lower := strings.Repeat("ab", 32)
	cases := map[string]struct {
		doc   string
		check func(config.Config) bool
	}{
		"pull 60":        {goodURL + "job_pull_seconds: 60\n", func(c config.Config) bool { return c.JobPullSeconds == 60 }},
		"pull 3600":      {goodURL + "job_pull_seconds: 3600\n", func(c config.Config) bool { return c.JobPullSeconds == 3600 }},
		"parallel 1":     {goodURL + "max_parallel_plugins: 1\n", func(c config.Config) bool { return c.MaxParallelPlugins == 1 }},
		"parallel 8":     {goodURL + "max_parallel_plugins: 8\n", func(c config.Config) bool { return c.MaxParallelPlugins == 8 }},
		"spool 1":        {goodURL + "spool_max_mb: 1\n", func(c config.Config) bool { return c.SpoolMaxMB == 1 }},
		"spool 50":       {goodURL + "spool_max_mb: 50\n", func(c config.Config) bool { return c.SpoolMaxMB == 50 }},
		"log debug":      {goodURL + "log_level: debug\n", func(c config.Config) bool { return c.LogLevel == "debug" }},
		"log warn":       {goodURL + "log_level: warn\n", func(c config.Config) bool { return c.LogLevel == "warn" }},
		"log error":      {goodURL + "log_level: error\n", func(c config.Config) bool { return c.LogLevel == "error" }},
		"pin lower":      {goodURL + "manager_spki_sha256: " + lower + "\n", func(c config.Config) bool { return c.ManagerSPKISHA256 == lower }},
		"pin upper":      {goodURL + "manager_spki_sha256: " + strings.ToUpper(lower) + "\n", func(c config.Config) bool { return c.ManagerSPKISHA256 == lower }},
		"pin digits":     {goodURL + "manager_spki_sha256: " + strings.Repeat("1", 64) + "\n", func(c config.Config) bool { return c.ManagerSPKISHA256 == strings.Repeat("1", 64) }},
		"pin quoted":     {goodURL + "manager_spki_sha256: \"" + lower + "\"\n", func(c config.Config) bool { return c.ManagerSPKISHA256 == lower }},
		"pin empty":      {goodURL + "manager_spki_sha256: \"\"\n", func(c config.Config) bool { return c.ManagerSPKISHA256 == "" }},
		"ca empty":       {goodURL + "ca_file: \"\"\n", func(c config.Config) bool { return c.CAFile == "" }},
		"ca null":        {goodURL + "ca_file:\n", func(c config.Config) bool { return c.CAFile == "" }},
		"HTTPS upper":    {"manager_url: HTTPS://Mgr.Example:8443\n", func(c config.Config) bool { return c.ManagerURL == "HTTPS://Mgr.Example:8443" }},
		"URL path":       {"manager_url: https://mgr.example/bitscan\n", func(c config.Config) bool { return c.ManagerURL == "https://mgr.example/bitscan" }},
		"IPv6 host":      {"manager_url: https://[2001:db8::1]:8443\n", func(c config.Config) bool { return c.ManagerURL == "https://[2001:db8::1]:8443" }},
		"quoted key":     {"\"manager_url\": https://mgr.example\n", func(c config.Config) bool { return c.ManagerURL == "https://mgr.example" }},
		"CRLF file":      {"manager_url: https://mgr.example\r\nlog_level: warn\r\n", func(c config.Config) bool { return c.LogLevel == "warn" }},
		"state_dir same": {goodURL + "state_dir: /var/lib/bitscan-agent\n", func(c config.Config) bool { return c.StateDir == "/var/lib/bitscan-agent" }},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			got, err := config.Parse([]byte(c.doc))
			if err != nil {
				t.Fatalf("refused: %v", err)
			}
			if !c.check(got) {
				t.Fatalf("loaded %+v", got)
			}
		})
	}
}

// A YAML alias bomb is refused (aliases are not allowed) and quickly.
func TestAliasBombBounded(t *testing.T) {
	var b strings.Builder
	b.WriteString(goodURL)
	b.WriteString("a0: &a0 [x, x, x, x, x, x, x, x, x, x]\n")
	for i := 1; i < 10; i++ {
		b.WriteString("a" + string(rune('0'+i)) + ": &a" + string(rune('0'+i)) + " [")
		for j := 0; j < 10; j++ {
			if j > 0 {
				b.WriteString(", ")
			}
			b.WriteString("*a" + string(rune('0'+i-1)))
		}
		b.WriteString("]\n")
	}
	done := make(chan error, 1)
	go func() { _, err := config.Parse([]byte(b.String())); done <- err }()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("alias bomb accepted")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Parse of an alias bomb did not return within 5 s")
	}
}

func writeFile(t *testing.T, dir, name, content string, mode os.FileMode) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(content), mode); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(p, mode); err != nil {
		t.Fatal(err)
	}
	return p
}

func loadWithin(t *testing.T, path string) (config.Config, error) {
	t.Helper()
	type res struct {
		c   config.Config
		err error
	}
	done := make(chan res, 1)
	go func() { c, err := config.Load(path); done <- res{c, err} }()
	select {
	case r := <-done:
		return r.c, r.err
	case <-time.After(5 * time.Second):
		t.Fatalf("Load(%s) did not return within 5 s", path)
		return config.Config{}, nil
	}
}

// REQ-092 (5): a missing or unreadable ca_file is refused; empty is the system store.
func TestLoadCAFile(t *testing.T) {
	dir := t.TempDir()
	ca := writeFile(t, dir, "ca.pem", "-----BEGIN CERTIFICATE-----\n", 0o644)
	ok := writeFile(t, dir, "ok.yaml", goodURL+"ca_file: "+ca+"\n", 0o640)
	if c, err := loadWithin(t, ok); err != nil || c.CAFile != ca {
		t.Fatalf("readable ca_file: %+v, %v", c, err)
	}
	refused := map[string]string{
		"missing path": filepath.Join(dir, "absent.pem"),
		"a directory":  dir,
	}
	for name, path := range specialFiles(t, dir) {
		refused[name] = path
	}
	if runtime.GOOS != "windows" && os.Geteuid() != 0 {
		refused["unreadable (0000, non-root)"] = writeFile(t, dir, "secret.pem", "x", 0o000)
	}
	for name, path := range refused {
		t.Run(name, func(t *testing.T) {
			p := writeFile(t, dir, "c.yaml", goodURL+"ca_file: "+path+"\n", 0o640)
			_, err := loadWithin(t, p)
			if err == nil {
				t.Fatalf("ca_file %s accepted", path)
			}
			if msg := err.Error(); !strings.Contains(msg, "ca_file") || strings.Contains(msg, "\n") {
				t.Fatalf("error %q", msg)
			}
		})
	}
	if os.Geteuid() == 0 {
		t.Log("unreadable-file case runs in the non-root (bstester) run only: root reads mode-0000 files")
	}
}

// Load refuses an unreadable or missing agent.yaml with one line and no content.
func TestLoadFileErrors(t *testing.T) {
	dir := t.TempDir()
	if _, err := loadWithin(t, filepath.Join(dir, "absent.yaml")); err == nil || !strings.HasPrefix(err.Error(), "agent.yaml: ") {
		t.Fatalf("missing file: %v", err)
	}
	bad := writeFile(t, dir, "bad.yaml", "manager_url: http://CANARY.example\n", 0o640)
	if _, err := loadWithin(t, bad); err == nil || strings.Contains(err.Error(), "CANARY") {
		t.Fatalf("http file: %v", err)
	}
}

// CHK-M4-023 (CHK-M4-342): Load never writes the file.
func TestLoadDoesNotWrite(t *testing.T) {
	dir := t.TempDir()
	p := writeFile(t, dir, "agent.yaml", string(specExample(t)), 0o640)
	old := time.Now().Add(-time.Hour).Truncate(time.Second)
	if err := os.Chtimes(p, old, old); err != nil {
		t.Fatal(err)
	}
	before, _ := os.Stat(p)
	content, _ := os.ReadFile(filepath.Clean(p))
	if _, err := loadWithin(t, p); err != nil {
		t.Fatal(err)
	}
	after, _ := os.Stat(p)
	content2, _ := os.ReadFile(filepath.Clean(p))
	if !bytes.Equal(content, content2) || before.Mode() != after.Mode() || !before.ModTime().Equal(after.ModTime()) {
		t.Fatalf("file changed: mode %v→%v mtime %v→%v", before.Mode(), after.Mode(), before.ModTime(), after.ModTime())
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 {
		t.Fatalf("Load created files: %v", entries)
	}
	// static: no write call in the package's non-test code
	files, _ := filepath.Glob("*.go")
	for _, fn := range files {
		if strings.HasSuffix(fn, "_test.go") {
			continue
		}
		src, _ := os.ReadFile(filepath.Clean(fn))
		// os.OpenFile is allowed only read-only (TASK-087 r1 opens ca_file
		// O_RDONLY|O_NONBLOCK); any write, create, truncate or append flag is not.
		for _, call := range []string{"WriteFile", "os.Create", "Rename", "Chmod", "Chown", "Remove", "Mkdir", "Truncate", "Symlink", "Link(", "O_WRONLY", "O_RDWR", "O_CREATE", "O_TRUNC", "O_APPEND", "syscall.Open", "unix.Open"} {
			if bytes.Contains(src, []byte(call)) {
				t.Errorf("%s contains %s", fn, call)
			}
		}
		for i, line := range strings.Split(string(src), "\n") {
			if strings.Contains(line, "OpenFile(") && !strings.Contains(line, "O_RDONLY") {
				t.Errorf("%s:%d: OpenFile without O_RDONLY on the same line: %s", fn, i+1, strings.TrimSpace(line))
			}
		}
	}
}

// CHK-M4-024: no environment variable changes the configuration.
func TestNoEnvironmentOverride(t *testing.T) {
	for _, k := range []string{"BITSCAN_MANAGER_URL", "MANAGER_URL", "BITSCAN_JOB_PULL_SECONDS", "BITSCAN_LOG_LEVEL", "BITSCAN_STATE_DIR", "BITSCAN_CA_FILE"} {
		t.Setenv(k, "http://CANARY.example")
	}
	t.Setenv("BITSCAN_JOB_PULL_SECONDS", "60")
	t.Setenv("BITSCAN_MANAGER_URL", "https://CANARY.example") // valid, so a re-checked override is caught too
	t.Setenv("BITSCAN_LOG_LEVEL", "debug")
	c, err := config.Parse(specExample(t))
	if err != nil {
		t.Fatal(err)
	}
	if c.ManagerURL != "https://mgr.example:8443" || c.JobPullSeconds != 300 || c.LogLevel != "info" || c.CAFile != "" {
		t.Fatalf("environment changed the config: %+v", c)
	}
	// Load too (the production path), not only Parse
	p := writeFile(t, t.TempDir(), "agent.yaml", string(specExample(t)), 0o640)
	c, err = loadWithin(t, p)
	if err != nil {
		t.Fatal(err)
	}
	if c.ManagerURL != "https://mgr.example:8443" || c.JobPullSeconds != 300 || c.LogLevel != "info" || c.CAFile != "" {
		t.Fatalf("environment changed the loaded config: %+v", c)
	}
	if _, err := config.Parse(nil); err == nil {
		t.Fatal("an empty file with BITSCAN_MANAGER_URL set was accepted")
	}
}
