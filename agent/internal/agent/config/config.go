// Package config reads /etc/bitscan/agent.yaml (TS §3.6) with the key rules
// agreed in #4. The agent only reads this file; postinst or root writes it
// (TS §3.1). Every refusal is one line naming the key, with no value in it.
package config

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"syscall"

	"go.yaml.in/yaml/v3"
)

const (
	// Path is the only place the agent reads its configuration from.
	Path = "/etc/bitscan/agent.yaml"
	// StateDir is fixed by the unit's ReadWritePaths= and the TS §3.7 file
	// table, so agent.yaml may only repeat it (#4).
	StateDir = "/var/lib/bitscan-agent"
	// HeartbeatSeconds is fixed at 300 (± 30 s jitter, TS §3.3) (#4).
	HeartbeatSeconds = 300
)

// Config holds the TS §3.6 keys. JobPullSeconds and MaxParallelPlugins apply
// only until a heartbeat response gives the manager's values.
type Config struct {
	ManagerURL         string
	CAFile             string // empty: the system CA store
	ManagerSPKISHA256  string // empty, or 64 lowercase hex characters (#79)
	StateDir           string
	HeartbeatSeconds   int
	JobPullSeconds     int
	MaxParallelPlugins int
	SpoolMaxMB         int
	LogLevel           string
}

var pinRe = regexp.MustCompile(`^[0-9a-fA-F]{64}$`)

func defaults() Config {
	return Config{
		StateDir:           StateDir,
		HeartbeatSeconds:   HeartbeatSeconds,
		JobPullSeconds:     300,
		MaxParallelPlugins: 2,
		SpoolMaxMB:         50,
		LogLevel:           "info",
	}
}

// Load reads and checks the file at path (Path in production) and checks
// that a non-empty ca_file is a readable regular file (REQ-092 (5)).
func Load(path string) (Config, error) {
	data, err := os.ReadFile(filepath.Clean(path))
	if err != nil {
		return Config{}, fmt.Errorf("agent.yaml: cannot read the file: %w", err)
	}
	c, err := Parse(data)
	if err != nil {
		return Config{}, err
	}
	if c.CAFile != "" {
		if err := readableFile(c.CAFile); err != nil {
			return Config{}, fmt.Errorf("agent.yaml: ca_file: %w", err)
		}
	}
	return c, nil
}

// readableFile checks the type before opening, because opening a FIFO for
// reading blocks until a writer appears. The open is non-blocking and the open
// file is checked again, so a path swapped to a FIFO or device in between is
// still refused without blocking.
func readableFile(path string) error {
	p := filepath.Clean(path)
	st, err := os.Stat(p)
	if err != nil {
		return errors.New("cannot open the file")
	}
	if !st.Mode().IsRegular() {
		return errors.New("not a regular file")
	}
	f, err := os.OpenFile(p, os.O_RDONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		return errors.New("cannot open the file")
	}
	defer func() { _ = f.Close() }()
	st, err = f.Stat()
	if err != nil || !st.Mode().IsRegular() {
		return errors.New("not a regular file")
	}
	return nil
}

// Parse checks one YAML document: a mapping of known keys, each at most once.
func Parse(data []byte) (Config, error) {
	c := defaults()
	dec := yaml.NewDecoder(bytes.NewReader(data))
	var doc yaml.Node
	if err := dec.Decode(&doc); err != nil && !errors.Is(err, io.EOF) {
		return Config{}, fmt.Errorf("agent.yaml: malformed YAML: %s", oneLine(err))
	}
	var extra yaml.Node
	if err := dec.Decode(&extra); !errors.Is(err, io.EOF) {
		return Config{}, errors.New("agent.yaml: more than one YAML document")
	}
	if len(doc.Content) > 0 {
		m := doc.Content[0]
		if m.Kind != yaml.MappingNode {
			return Config{}, errors.New("agent.yaml: the file is not a mapping of keys")
		}
		seen := map[string]bool{}
		for i := 0; i+1 < len(m.Content); i += 2 {
			key, val := m.Content[i].Value, m.Content[i+1]
			if seen[key] {
				return Config{}, fmt.Errorf("agent.yaml: %s: key given twice", safeKey(key))
			}
			seen[key] = true
			if err := c.set(key, val); err != nil {
				return Config{}, fmt.Errorf("agent.yaml: %s: %w", safeKey(key), err)
			}
		}
	}
	if err := c.check(); err != nil {
		return Config{}, err
	}
	return c, nil
}

func (c *Config) set(key string, val *yaml.Node) error {
	switch key {
	case "manager_url":
		return str(val, &c.ManagerURL)
	case "ca_file":
		return str(val, &c.CAFile)
	case "manager_spki_sha256":
		return str(val, &c.ManagerSPKISHA256)
	case "state_dir":
		return str(val, &c.StateDir)
	case "log_level":
		return str(val, &c.LogLevel)
	case "heartbeat_seconds":
		return integer(val, &c.HeartbeatSeconds)
	case "job_pull_seconds":
		return integer(val, &c.JobPullSeconds)
	case "max_parallel_plugins":
		return integer(val, &c.MaxParallelPlugins)
	case "spool_max_mb":
		return integer(val, &c.SpoolMaxMB)
	}
	return errors.New("unknown key")
}

// str takes a scalar's text as written (a pin made only of digits resolves
// as !!int in YAML); null means empty.
func str(n *yaml.Node, out *string) error {
	if n.Kind != yaml.ScalarNode {
		return errors.New("must be a single value")
	}
	if n.ShortTag() == "!!null" {
		*out = ""
		return nil
	}
	*out = n.Value
	return nil
}

func integer(n *yaml.Node, out *int) error {
	if n.Kind != yaml.ScalarNode || n.ShortTag() != "!!int" {
		return errors.New("must be a whole number")
	}
	if err := n.Decode(out); err != nil {
		return errors.New("must be a whole number")
	}
	return nil
}

func (c *Config) check() error {
	u, err := url.Parse(c.ManagerURL)
	switch {
	case c.ManagerURL == "":
		return errors.New("agent.yaml: manager_url: missing")
	case err != nil || u.Scheme != "https" || u.Host == "" || u.Hostname() == "":
		// url.Parse lower-cases the scheme, so HTTPS:// is accepted (lead ruling).
		return errors.New("agent.yaml: manager_url: must be an https:// URL with a host")
	case c.ManagerSPKISHA256 != "" && !pinRe.MatchString(c.ManagerSPKISHA256):
		return errors.New("agent.yaml: manager_spki_sha256: must be empty or 64 hex characters")
	case c.StateDir != StateDir:
		return errors.New("agent.yaml: state_dir: must be " + StateDir)
	case c.HeartbeatSeconds != HeartbeatSeconds:
		return errors.New("agent.yaml: heartbeat_seconds: must be 300")
	case c.JobPullSeconds < 60 || c.JobPullSeconds > 3600:
		return errors.New("agent.yaml: job_pull_seconds: must be 60 to 3600")
	case c.MaxParallelPlugins < 1 || c.MaxParallelPlugins > 8:
		return errors.New("agent.yaml: max_parallel_plugins: must be 1 to 8")
	case c.SpoolMaxMB < 1 || c.SpoolMaxMB > 50:
		return errors.New("agent.yaml: spool_max_mb: must be 1 to 50")
	case !slices.Contains([]string{"debug", "info", "warn", "error"}, c.LogLevel):
		return errors.New("agent.yaml: log_level: must be debug, info, warn or error")
	}
	c.ManagerSPKISHA256 = strings.ToLower(c.ManagerSPKISHA256)
	return nil
}

// safeKey names an unknown key without echoing arbitrary file content.
func safeKey(key string) string {
	if key == "" || len(key) > 64 || strings.ContainsFunc(key, func(r rune) bool { return r < 0x20 || r > 0x7e }) {
		return "(unprintable key)"
	}
	return key
}

func oneLine(err error) string {
	return strings.Join(strings.Fields(err.Error()), " ")
}
