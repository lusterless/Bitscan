module bitscan.local/agent

go 1.27.2

// PD-25 (a): yaml/v3 is linked into bitscan-agent (agent.yaml); jsonschema/v6
// is imported only by _test.go files (the TP-M4-01 contract test), so it and
// golang.org/x/text are never linked into a shipped binary.
// PD-41 (a): golang.org/x/sys is pinned here and in go.sum, for the Linux
// calls of internal/runner, internal/sdsock and internal/capread only.
require (
	github.com/santhosh-tekuri/jsonschema/v6 v6.0.3
	go.yaml.in/yaml/v3 v3.0.5
	golang.org/x/sys v0.49.0
)

require golang.org/x/text v0.14.0 // indirect
