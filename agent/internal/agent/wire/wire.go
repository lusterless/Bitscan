// Package wire holds the agent side of the frozen agent wire contract: TS §6.5
// and the agent components of manager/openapi.json (#60 field table).
//
// Every key is always sent: nullable keys are pointers that encode as null,
// and no json tag drops empty values. Tag `wire` carries the schema bounds
// that Validate checks: min/max (code points for strings, items for arrays,
// value for integers), nul (U+0000 allowed), uniq, only=<kind> (key present
// only for that job kind).
package wire

import (
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"slices"
	"strings"
	"time"
)

// 9007199254740991 below is 2^53 − 1, the bound of every 64-bit counter
// (decisions 2026-10-23).

type EnrolRequest struct {
	Hostname     string    `json:"hostname" wire:"min=1,max=255"`
	MachineID    MachineID `json:"machine_id"`
	AgentVersion string    `json:"agent_version" wire:"min=1,max=32"`
	OsID         *string   `json:"os_id" wire:"max=32"`
	OsVersionID  *string   `json:"os_version_id" wire:"max=16"`
	OsPrettyName *string   `json:"os_pretty_name" wire:"max=128"`
}

type EnrolResponse struct {
	AgentID    UUID        `json:"agent_id"`
	AgentToken AgentToken  `json:"agent_token"`
	IssuedAt   Time        `json:"issued_at"`
	ExpiresAt  Time        `json:"expires_at"`
	Status     EnrolStatus `json:"status"`
}

type HeartbeatRequest struct {
	AgentVersion  string       `json:"agent_version" wire:"min=1,max=32"`
	UptimeS       int64        `json:"uptime_s" wire:"min=0,max=9007199254740991"`
	LastPullAt    *Time        `json:"last_pull_at"`
	CurrentJobID  *UUID        `json:"current_job_id"`
	SpoolBytes    int64        `json:"spool_bytes" wire:"min=0,max=9007199254740991"`
	LastError     *string      `json:"last_error" wire:"max=1024"`
	RunnerHelpers []HelperName `json:"runner_helpers" wire:"max=8,uniq"`
	Clock         Time         `json:"clock"`
}

type HeartbeatResponse struct {
	JobPullSeconds     int  `json:"job_pull_seconds" wire:"min=60,max=3600"`
	MaxParallelPlugins int  `json:"max_parallel_plugins" wire:"min=1,max=8"`
	ServerTime         Time `json:"server_time"`
}

type JobsResponse struct {
	Jobs []Job `json:"jobs" wire:"max=10"`
}

// Job is an InventoryJob or a ComplianceJob; an inventory job has no plugins
// or redaction_patterns key (TS §6.5 L1182).
type Job struct {
	JobID             UUID         `json:"job_id"`
	AgentID           UUID         `json:"agent_id"`
	Kind              JobKind      `json:"kind"`
	PickupBy          Time         `json:"pickup_by"`
	Plugins           []PluginSpec `json:"plugins" wire:"max=5000,only=compliance"`
	RedactionPatterns []string     `json:"redaction_patterns" wire:"max=50,nul,only=compliance"`
}

type PluginSpec struct {
	PluginUUID UUID   `json:"plugin_uuid"`
	Execute    string `json:"execute" wire:"min=1,nul"`
	TimeoutS   int    `json:"timeout_s" wire:"min=1,max=600"`
}

type ResultsRequest struct {
	Results []ResultItem `json:"results" wire:"max=50"`
	Final   bool         `json:"final"`
}

// ResultItem: stdout and stderr may hold U+0000 until M9 (TASK-048 plan).
type ResultItem struct {
	PluginUUID UUID         `json:"plugin_uuid"`
	ExitCode   *int64       `json:"exit_code" wire:"min=-2147483648,max=2147483647"`
	Stdout     string       `json:"stdout" wire:"nul"`
	Stderr     string       `json:"stderr" wire:"nul"`
	StartedAt  Time         `json:"started_at"`
	FinishedAt Time         `json:"finished_at"`
	TimedOut   bool         `json:"timed_out"`
	Truncated  bool         `json:"truncated"`
	Error      *ResultError `json:"error"`
}

type ResultsResponse struct {
	Accepted   int64 `json:"accepted" wire:"min=0"`
	Duplicates int64 `json:"duplicates" wire:"min=0"`
}

type InventoryBody struct {
	OsInfo     OsInfo        `json:"os_info"`
	Packages   []PackageItem `json:"packages" wire:"max=50000"`
	ListSHA256 SHA256Hex     `json:"list_sha256"`
}

// OsInfo.Raw holds only map[string]any, []any, string, json.Number, float64,
// int, int64, bool and nil (RawValue); see validateRaw.
type OsInfo struct {
	OsID          *string        `json:"os_id" wire:"max=32"`
	OsVersionID   *string        `json:"os_version_id" wire:"max=16"`
	OsPrettyName  *string        `json:"os_pretty_name" wire:"max=128"`
	KernelRelease *string        `json:"kernel_release" wire:"max=64"`
	Architecture  *string        `json:"architecture" wire:"max=16"`
	CPUCount      *int64         `json:"cpu_count" wire:"min=0,max=2147483647"`
	MemoryMB      *int64         `json:"memory_mb" wire:"min=0,max=2147483647"`
	IPAddresses   []IPAddress    `json:"ip_addresses" wire:"max=256"`
	UptimeS       *int64         `json:"uptime_s" wire:"min=0,max=9007199254740991"`
	Raw           map[string]any `json:"raw"`
}

type PackageItem struct {
	Name            string  `json:"name" wire:"min=1,max=255"`
	Version         string  `json:"version" wire:"min=1,max=255"`
	Architecture    string  `json:"architecture" wire:"min=1,max=16"`
	Status          string  `json:"status" wire:"min=1,max=64"`
	Source          *string `json:"source" wire:"max=255"`
	InstalledSizeKB *int64  `json:"installed_size_kb" wire:"min=0,max=2147483647"`
}

// RotateRequest is the empty object: rotate takes no body (#60).
type RotateRequest struct{}

type RotateResponse struct {
	AgentToken AgentToken `json:"agent_token"`
	IssuedAt   Time       `json:"issued_at"`
	ExpiresAt  Time       `json:"expires_at"`
}

// Problem is an RFC 9457 body; it is decoded leniently (DecodeProblem).
type Problem struct {
	Type     string `json:"type"`
	Title    string `json:"title"`
	Status   int    `json:"status"`
	Detail   string `json:"detail"`
	Instance string `json:"instance"`
}

var (
	uuidRe    = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
	machineRe = regexp.MustCompile(`^[0-9a-f]{32}$`)
	tokenRe   = regexp.MustCompile(`^bsa_[A-Za-z0-9_-]{43}$`)
	sha256Re  = regexp.MustCompile(`^[0-9a-f]{64}$`)
	helperRe  = regexp.MustCompile(`^[a-z][a-z0-9_-]{0,31}$`)
	timeRe    = regexp.MustCompile(`^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])[Tt]([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{1,9})?([Zz]|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$`)
	// The OsInfo.ip_addresses item pattern of manager/openapi.json, verbatim.
	ipRe = regexp.MustCompile(`^(((25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])([.](25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3})(/(3[0-2]|[12]?[0-9]))?|(([0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}|([0-9A-Fa-f]{1,4}:){1,7}:|([0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}|([0-9A-Fa-f]{1,4}:){1,5}(:[0-9A-Fa-f]{1,4}){1,2}|([0-9A-Fa-f]{1,4}:){1,4}(:[0-9A-Fa-f]{1,4}){1,3}|([0-9A-Fa-f]{1,4}:){1,3}(:[0-9A-Fa-f]{1,4}){1,4}|([0-9A-Fa-f]{1,4}:){1,2}(:[0-9A-Fa-f]{1,4}){1,5}|[0-9A-Fa-f]{1,4}:(:[0-9A-Fa-f]{1,4}){1,6}|:((:[0-9A-Fa-f]{1,4}){1,7}|:)|([0-9A-Fa-f]{1,4}:){6}(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])([.](25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3}|::([Ff]{4}(:0{1,4})?:)?(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])([.](25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3}|([0-9A-Fa-f]{1,4}:){1,4}:(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])([.](25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3})(/(12[0-8]|1[01][0-9]|[1-9]?[0-9]))?)$`)

	errFormat = errors.New("bad format")
	errEnum   = errors.New("not an allowed value")
)

func match(re *regexp.Regexp, s string) error {
	if !re.MatchString(s) {
		return errFormat
	}
	return nil
}

func oneOf(s string, allowed ...string) error {
	if slices.Contains(allowed, s) {
		return nil
	}
	return errEnum
}

// UUID is hyphenated 8-4-4-4-12 hex; either case is accepted on input and it
// is held and sent in lowercase.
type UUID string

func (u UUID) check() error { return match(uuidRe, string(u)) }

func (u UUID) MarshalJSON() ([]byte, error) { return json.Marshal(strings.ToLower(string(u))) }

func (u *UUID) UnmarshalJSON(b []byte) error {
	var s string
	if err := json.Unmarshal(b, &s); err != nil {
		return fmt.Errorf("uuid: %w", err)
	}
	*u = UUID(strings.ToLower(s))
	return nil
}

// Time is an RFC 3339 timestamp with an offset (fractions allowed). A decoded
// value keeps its text so it re-encodes unchanged; NewTime values are sent in
// UTC with "Z".
type Time struct {
	t    time.Time
	text string
}

func NewTime(t time.Time) Time { return Time{t: t} }

func (t Time) Time() time.Time { return t.t }

func (t Time) MarshalJSON() ([]byte, error) {
	if t.text != "" {
		return json.Marshal(t.text)
	}
	return json.Marshal(t.t.UTC().Format(time.RFC3339Nano))
}

func (t *Time) UnmarshalJSON(b []byte) error {
	var s string
	if err := json.Unmarshal(b, &s); err != nil {
		return fmt.Errorf("timestamp: %w", err)
	}
	if !timeRe.MatchString(s) {
		return errors.New("timestamp: not RFC 3339 with an offset")
	}
	p, err := time.Parse(time.RFC3339Nano, strings.ToUpper(s))
	if err != nil {
		return fmt.Errorf("timestamp: %w", err)
	}
	*t = Time{t: p, text: s}
	return nil
}

// AgentToken is a bsa_ token. It never prints: fmt and log verbs show a fixed
// placeholder; use string(tok) only to build the Authorization header or the
// state file.
type AgentToken string

func (a AgentToken) check() error     { return match(tokenRe, string(a)) }
func (AgentToken) String() string     { return "bsa_[redacted]" }
func (a AgentToken) GoString() string { return a.String() }
func (m MachineID) check() error      { return match(machineRe, string(m)) }
func (h SHA256Hex) check() error      { return match(sha256Re, string(h)) }
func (h HelperName) check() error     { return match(helperRe, string(h)) }
func (a IPAddress) check() error      { return match(ipRe, string(a)) }
func (s EnrolStatus) check() error    { return oneOf(string(s), "enrolled", "awaiting_approval") }
func (k JobKind) check() error        { return oneOf(string(k), "inventory", "compliance") }
func (e ResultError) check() error    { return oneOf(string(e), "spool_overflow", "runner_unavailable") }

func (j Job) check() error {
	if j.Kind == KindCompliance {
		if len(j.Plugins) == 0 || j.RedactionPatterns == nil {
			return errors.New("compliance job needs plugins (at least 1) and redaction_patterns")
		}
	} else if j.Plugins != nil || j.RedactionPatterns != nil {
		return errors.New("inventory job has no plugins or redaction_patterns")
	}
	return nil
}

type (
	MachineID   string // 32 lowercase hex characters, the machine-id(5) form
	SHA256Hex   string // 64 lowercase hex characters
	HelperName  string
	IPAddress   string // address with an optional prefix length, no zone
	EnrolStatus string
	JobKind     string
	ResultError string
)

const (
	StatusEnrolled         EnrolStatus = "enrolled"
	StatusAwaitingApproval EnrolStatus = "awaiting_approval"
	KindInventory          JobKind     = "inventory"
	KindCompliance         JobKind     = "compliance"
	ErrSpoolOverflow       ResultError = "spool_overflow"
	ErrRunnerUnavailable   ResultError = "runner_unavailable"
)
