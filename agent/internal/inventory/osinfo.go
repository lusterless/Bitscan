package inventory

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"

	"bitscan.local/agent/internal/agent/wire"
)

// Files read without a command (TS §3.4 L234). Variables only so in-package
// tests can point them at fixtures.
var (
	osReleasePath = "/etc/os-release"
	meminfoPath   = "/proc/meminfo"
	uptimePath    = "/proc/uptime"
)

// uname gives `uname -r` and `uname -m`; osinfo_linux.go sets it.
var uname = func() (release, machine string, err error) { return "", "", errFailed }

const (
	maxFileBytes = 1 << 20
	rawCap       = 256 << 10 // os_info.raw as compact UTF-8 JSON (TS §3.4 L240)
	maxAddresses = 256       // OsInfo.ip_addresses maxItems
)

// Fixed raw.errors reasons besides the command ones (#77 (d), (e)).
const (
	reasonUnreadable = "unreadable"
	reasonUnparsable = "unparsable"
	reasonContract   = "value outside the contract"
	reasonTooMany    = "more than 256 addresses"
	reasonRawInvalid = "dropped: outside the contract"
	reasonRawLimit   = "dropped: raw over 256 KiB"
)

var envKeyRe = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)

// osCollector builds one os_info. errs is raw.errors: source or field name to
// a fixed reason.
type osCollector struct {
	info wire.OsInfo
	raw  map[string]any
	errs map[string]any
}

// CollectOSInfo reads os_info from the TS §3.4 sources as #77 defines. The
// value it returns always passes the contract: a source that fails leaves its
// fields null (ip_addresses empty) and names itself in raw.errors. The only
// error is ctx ending.
func CollectOSInfo(ctx context.Context) (wire.OsInfo, error) {
	c := &osCollector{
		info: wire.OsInfo{IPAddresses: []wire.IPAddress{}},
		raw:  map[string]any{},
		errs: map[string]any{},
	}
	c.osRelease(osReleasePath)
	c.kernel()
	setField(c, "cpu_count", func(o *wire.OsInfo) **int64 { return &o.CPUCount }, int64(runtime.NumCPU())) // nproc: honours the affinity mask
	c.memory()
	c.uptime()
	if err := c.hostnamectl(ctx); err != nil {
		return wire.OsInfo{}, err
	}
	if err := c.addresses(ctx); err != nil {
		return wire.OsInfo{}, err
	}
	c.finishRaw()
	return c.info, nil
}

// setField sets one os_info field to v, or leaves it null with a reason if v
// would fail the contract (#77 (d)). It checks v with wire.Validate itself.
func setField[T any](c *osCollector, name string, field func(*wire.OsInfo) **T, v T) {
	probe := wire.OsInfo{IPAddresses: []wire.IPAddress{}, Raw: map[string]any{}}
	*field(&probe) = &v
	if wire.Validate(probe) != nil {
		c.errs[name] = reasonContract
		return
	}
	*field(&c.info) = &v
}

// ReadOSRelease returns ID, VERSION_ID and PRETTY_NAME from the os-release(5)
// file at path, with the same parsing and contract bounds as os_info (the
// enrolment request uses the same fields, TS §3.2 step 1). Each is nil when
// the file is unreadable, the key is absent or the value is outside the
// contract. Nothing is executed.
func ReadOSRelease(path string) (osID, osVersionID, osPrettyName *string) {
	c := &osCollector{
		info: wire.OsInfo{IPAddresses: []wire.IPAddress{}},
		raw:  map[string]any{},
		errs: map[string]any{},
	}
	c.osRelease(path)
	return c.info.OsID, c.info.OsVersionID, c.info.OsPrettyName
}

func (c *osCollector) osRelease(path string) {
	data, err := readSmall(path)
	if err != nil {
		c.errs["os_release"] = reasonUnreadable
		return
	}
	kv := parseOSRelease(data)
	all := make(map[string]any, len(kv))
	for k, v := range kv {
		all[k] = v
	}
	c.raw["os_release"] = all
	for _, f := range []struct {
		name, key string
		field     func(*wire.OsInfo) **string
	}{
		{"os_id", "ID", func(o *wire.OsInfo) **string { return &o.OsID }},
		{"os_version_id", "VERSION_ID", func(o *wire.OsInfo) **string { return &o.OsVersionID }},
		{"os_pretty_name", "PRETTY_NAME", func(o *wire.OsInfo) **string { return &o.OsPrettyName }},
	} {
		if v, ok := kv[f.key]; ok {
			setField(c, f.name, f.field, v)
		}
	}
}

// parseOSRelease reads os-release(5): KEY=VALUE lines, values optionally in
// double quotes (with \ escaping $ " \ `) or single quotes.
func parseOSRelease(data []byte) map[string]string {
	kv := map[string]string{}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		k, v, ok := strings.Cut(line, "=")
		if !ok || strings.HasPrefix(line, "#") || !envKeyRe.MatchString(k) {
			continue
		}
		if len(v) >= 2 && (v[0] == '"' || v[0] == '\'') && v[len(v)-1] == v[0] {
			quote := v[0]
			v = v[1 : len(v)-1]
			if quote == '"' {
				var b strings.Builder
				for i := 0; i < len(v); i++ {
					if v[i] == '\\' && i+1 < len(v) && strings.IndexByte("$\"\\`", v[i+1]) >= 0 {
						i++
					}
					b.WriteByte(v[i])
				}
				v = b.String()
			}
		}
		kv[k] = v
	}
	return kv
}

func (c *osCollector) kernel() {
	release, machine, err := uname()
	if err != nil {
		c.errs["uname"] = reasonUnreadable
		return
	}
	setField(c, "kernel_release", func(o *wire.OsInfo) **string { return &o.KernelRelease }, release)
	setField(c, "architecture", func(o *wire.OsInfo) **string { return &o.Architecture }, machine)
}

func (c *osCollector) memory() {
	data, err := readSmall(meminfoPath)
	if err != nil {
		c.errs["meminfo"] = reasonUnreadable
		return
	}
	for _, line := range strings.Split(string(data), "\n") {
		f := strings.Fields(line)
		if len(f) == 3 && f[0] == "MemTotal:" && f[2] == "kB" {
			if kb, err := strconv.ParseInt(f[1], 10, 64); err == nil && kb >= 0 {
				c.raw["meminfo"] = map[string]any{"MemTotal_kb": kb}
				setField(c, "memory_mb", func(o *wire.OsInfo) **int64 { return &o.MemoryMB }, kb/1024)
				return
			}
		}
	}
	c.errs["meminfo"] = reasonUnparsable
}

func (c *osCollector) uptime() {
	data, err := readSmall(uptimePath)
	if err != nil {
		c.errs["uptime"] = reasonUnreadable
		return
	}
	f := strings.Fields(string(data))
	if len(f) > 0 {
		whole, _, _ := strings.Cut(f[0], ".")
		if s, err := strconv.ParseInt(whole, 10, 64); err == nil && s >= 0 {
			setField(c, "uptime_s", func(o *wire.OsInfo) **int64 { return &o.UptimeS }, s)
			return
		}
	}
	c.errs["uptime"] = reasonUnparsable
}

// hostnamectl keeps the plain status output as "Key: value" pairs in raw;
// no os_info field comes from it.
func (c *osCollector) hostnamectl(ctx context.Context) error {
	out, err := hostnamectlCmd.run(ctx)
	if err != nil {
		return c.commandFailed(ctx, hostnamectlCmd, err)
	}
	pairs := map[string]any{}
	for _, line := range strings.Split(string(out), "\n") {
		k, v, ok := strings.Cut(line, ":")
		if k = strings.TrimSpace(k); ok && k != "" {
			pairs[k] = strings.TrimSpace(v)
		}
	}
	c.raw["hostnamectl"] = pairs
	return nil
}

// addresses keeps the parsed `ip -j addr` in raw and derives ip_addresses:
// every addr_info "local" with "/prefixlen", every interface and family (#77
// (b)). An addr_info item without "local" holds no address and is skipped.
// ip_addresses is never null in the contract: on any failure it stays empty
// with one reason under raw.errors["ip_addresses"] (lead ruling 2026-10-24).
func (c *osCollector) addresses(ctx context.Context) error {
	out, err := ipAddrCmd.run(ctx)
	if err != nil {
		if err := c.commandFailed(ctx, ipAddrCmd, err); err != nil {
			return err
		}
		c.errs["ip_addresses"] = c.errs[ipAddrCmd.source]
		return nil
	}
	dec := json.NewDecoder(bytes.NewReader(out))
	dec.UseNumber()
	var parsed []any
	if err := dec.Decode(&parsed); err != nil {
		c.errs[ipAddrCmd.source] = reasonUnparsable
		c.errs["ip_addresses"] = reasonUnparsable
		return nil
	}
	c.raw[ipAddrCmd.source] = parsed
	addrs := []wire.IPAddress{}
	for _, iface := range parsed {
		m, _ := iface.(map[string]any)
		infos, _ := m["addr_info"].([]any)
		for _, item := range infos {
			ai, _ := item.(map[string]any)
			local, ok := ai["local"].(string)
			if !ok {
				continue
			}
			if prefix, ok := ai["prefixlen"].(json.Number); ok {
				local += "/" + prefix.String()
			}
			addrs = append(addrs, wire.IPAddress(local))
		}
	}
	probe := wire.OsInfo{IPAddresses: addrs, Raw: map[string]any{}}
	switch {
	case len(addrs) > maxAddresses:
		c.errs["ip_addresses"] = reasonTooMany
	case wire.Validate(probe) != nil:
		c.errs["ip_addresses"] = reasonContract
	default:
		c.info.IPAddresses = addrs
	}
	return nil
}

// commandFailed records a failed command under its source, or returns the
// error when ctx itself ended (the collection stops).
func (c *osCollector) commandFailed(ctx context.Context, cmd command, err error) error {
	if ctx.Err() != nil {
		return fmt.Errorf("inventory: os_info: %w", err)
	}
	reason := errFailed.Error()
	for _, known := range []error{errNotFound, errTimedOut, errTooLarge} {
		if errors.Is(err, known) {
			reason = known.Error()
		}
	}
	c.errs[cmd.source] = reason
	return nil
}

func (c *osCollector) finishRaw() {
	fitRaw(c.raw, c.errs)
	c.info.Raw = c.raw
}

// fitRaw drops raw entries the contract refuses where they sit (U+0000,
// nesting past the manager's depth), then the largest entries until raw is
// at most 256 KiB, each with a reason in errs (#77 (d)). errs is stored as
// raw["errors"], which is always sent.
func fitRaw(raw, errs map[string]any) {
	delete(raw, "errors")
	for k, v := range raw {
		probe := wire.InventoryBody{
			OsInfo:     wire.OsInfo{IPAddresses: []wire.IPAddress{}, Raw: map[string]any{k: v}},
			Packages:   []wire.PackageItem{},
			ListSHA256: wire.SHA256Hex(strings.Repeat("0", 64)),
		}
		if wire.Validate(probe) != nil {
			delete(raw, k)
			errs[k] = reasonRawInvalid
		}
	}
	raw["errors"] = errs
	for compactSize(raw) > rawCap {
		largest, size := "", -1
		for k, v := range raw {
			if s := compactSize(v); k != "errors" && (s > size || (s == size && k < largest)) {
				largest, size = k, s
			}
		}
		if largest == "" {
			break
		}
		delete(raw, largest)
		errs[largest] = reasonRawLimit
	}
}

// compactSize is the length of v as compact JSON without HTML escaping. It
// is never below the manager's measure (json.dumps, ensure_ascii=False).
func compactSize(v any) int {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return rawCap + 1
	}
	return buf.Len() - 1 // the encoder's newline
}

// readSmall reads a whole file of at most maxFileBytes (proc files report
// size 0, so the length is checked while reading).
func readSmall(path string) ([]byte, error) {
	f, err := os.Open(filepath.Clean(path))
	if err != nil {
		return nil, fmt.Errorf("inventory: open: %w", err)
	}
	defer func() { _ = f.Close() }()
	data, err := io.ReadAll(io.LimitReader(f, maxFileBytes+1))
	if err != nil {
		return nil, fmt.Errorf("inventory: read: %w", err)
	}
	if len(data) > maxFileBytes {
		return nil, errTooLarge
	}
	return data, nil
}
