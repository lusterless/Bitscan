//go:build linux

package inventory

// TP-M4-09 (TASK-094; REQ-100; TS §3.4 L232-L240, #35, #77; lead rulings
// 2026-10-24 TASK-094/095 Q1). Expected values come from #35 and #77, never
// from the code: the three fixed commands, their limits and environment;
// os_info derived from os-release, uname, nproc, MemTotal / 1024 rounded down,
// /proc/uptime rounded down and every `ip -j addr` address with /prefixlen; a
// failed source gives null fields and a fixed reason in raw.errors; a value
// outside the contract is null with a reason; ip_addresses is never null.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"bitscan.local/agent/internal/agent/wire"
)

// ---- shared helpers (prefix "it") ------------------------------------------

var (
	itSchemaOnce sync.Once
	itSchemas    map[string]*jsonschema.Schema
	itSchemaErr  error
)

// itSchema compiles a component of manager/openapi.json (JSON Schema 2020-12,
// format assertion on), the same validator as the TP-M4-01 contract test.
func itSchema(t *testing.T, name string) *jsonschema.Schema {
	t.Helper()
	itSchemaOnce.Do(func() {
		itSchemas = map[string]*jsonschema.Schema{}
		p := filepath.Join(filepath.Dir(itModuleRoot(t)), "manager", "openapi.json")
		data, err := os.ReadFile(filepath.Clean(p))
		if err != nil {
			itSchemaErr = err
			return
		}
		doc, err := jsonschema.UnmarshalJSON(bytes.NewReader(data))
		if err != nil {
			itSchemaErr = err
			return
		}
		const url = "file:///bitscan/manager/openapi.json"
		c := jsonschema.NewCompiler()
		c.DefaultDraft(jsonschema.Draft2020)
		c.AssertFormat()
		if itSchemaErr = c.AddResource(url, doc); itSchemaErr != nil {
			return
		}
		for _, n := range []string{"InventoryBody", "OsInfo"} {
			s, err := c.Compile(url + "#/components/schemas/" + n)
			if err != nil {
				itSchemaErr = err
				return
			}
			itSchemas[n] = s
		}
	})
	if itSchemaErr != nil {
		t.Fatalf("openapi.json: %v", itSchemaErr)
	}
	return itSchemas[name]
}

func itValidate(t *testing.T, component string, v any) error {
	t.Helper()
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		t.Fatal(err)
	}
	inst, err := jsonschema.UnmarshalJSON(bytes.NewReader(buf.Bytes()))
	if err != nil {
		t.Fatal(err)
	}
	return itSchema(t, component).Validate(inst)
}

// itBodyValid checks os_info inside a minimal InventoryBody against the schema
// (the body root is where the 32-container depth and the raw limit apply).
func itBodyValid(t *testing.T, info wire.OsInfo) {
	t.Helper()
	body := wire.InventoryBody{OsInfo: info, Packages: []wire.PackageItem{},
		ListSHA256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
	if err := itValidate(t, "InventoryBody", body); err != nil {
		t.Fatalf("os_info does not validate against InventoryBody: %v", err)
	}
	if err := wire.Validate(body); err != nil {
		t.Fatalf("os_info refused by wire.Validate: %v", err)
	}
	if n := compactSize(info.Raw); n > 262144 {
		t.Fatalf("raw is %d bytes compact, over 262,144", n)
	}
}

func itModuleRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("go.mod not found")
		}
		dir = parent
	}
}

func itFile(t *testing.T, name, content string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(p, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

// itScript writes an executable /bin/sh test program (a stand-in for one of
// the fixed commands; the agent code runs it without a shell of its own).
func itScript(t *testing.T, body string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "fake")
	if err := os.WriteFile(p, []byte("#!/bin/sh\n"+body+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Chmod(p, 0o700); err != nil { // the test program must be executable
		t.Fatal(err)
	}
	return p
}

// itSwap replaces the package's inputs for one test and restores them after.
type itInputs struct {
	osRelease, meminfo, uptime string
	uname                      func() (string, string, error)
	hostnamectl, ip            *command
}

func itSwap(t *testing.T, in itInputs) {
	t.Helper()
	so, sm, su, sn, sh, si := osReleasePath, meminfoPath, uptimePath, uname, hostnamectlCmd, ipAddrCmd
	t.Cleanup(func() {
		osReleasePath, meminfoPath, uptimePath, uname, hostnamectlCmd, ipAddrCmd = so, sm, su, sn, sh, si
	})
	if in.osRelease != "" {
		osReleasePath = in.osRelease
	}
	if in.meminfo != "" {
		meminfoPath = in.meminfo
	}
	if in.uptime != "" {
		uptimePath = in.uptime
	}
	if in.uname != nil {
		uname = in.uname
	}
	if in.hostnamectl != nil {
		hostnamectlCmd = *in.hostnamectl
	}
	if in.ip != nil {
		ipAddrCmd = *in.ip
	}
}

func itCat(t *testing.T, source, content string) *command { // a command printing content
	return &command{source: source, paths: []string{"/bin/cat"}, args: []string{itFile(t, source+".out", content)}, limit: 5 * time.Second, maxOut: 1 << 20}
}

func itStr(p *string) string {
	if p == nil {
		return "<null>"
	}
	return *p
}

func itInt(p *int64) string {
	if p == nil {
		return "<null>"
	}
	return strconv.FormatInt(*p, 10)
}

func itErrs(info wire.OsInfo) map[string]any {
	e, _ := info.Raw["errors"].(map[string]any)
	return e
}

func itCollect(t *testing.T) wire.OsInfo {
	t.Helper()
	info, err := CollectOSInfo(context.Background())
	if err != nil {
		t.Fatalf("CollectOSInfo: %v", err)
	}
	if info.IPAddresses == nil {
		t.Fatal("ip_addresses is nil (would encode as null; the contract allows no null)")
	}
	return info
}

const itOSRelease = `PRETTY_NAME="Ubuntu 24.04.1 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.1 LTS (Noble Numbat)"
ID=ubuntu
ID_LIKE=debian
`

const itIPJSON = `[{"ifindex":1,"ifname":"lo","flags":["LOOPBACK","UP"],"mtu":65536,"addr_info":[
 {"family":"inet","local":"127.0.0.1","prefixlen":8,"scope":"host","label":"lo","valid_life_time":4294967295},
 {"family":"inet6","local":"::1","prefixlen":128,"scope":"host"}]},
{"ifindex":2,"ifname":"eth0","mtu":1500,"addr_info":[
 {"family":"inet","local":"10.0.0.5","prefixlen":24,"broadcast":"10.0.0.255","scope":"global"},
 {"family":"inet6","local":"fe80::1","prefixlen":64,"scope":"link"},
 {"family":"inet6","prefixlen":64},
 {"family":"inet","local":"192.0.2.9"}]},
{"ifindex":3,"ifname":"dummy0","addr_info":[]}]`

func itFixtureHost(t *testing.T) {
	t.Helper()
	itSwap(t, itInputs{
		osRelease:   itFile(t, "os-release", itOSRelease),
		meminfo:     itFile(t, "meminfo", "MemFree:         123 kB\nMemTotal:        8388607 kB\nBuffers: 1 kB\n"),
		uptime:      itFile(t, "uptime", "12345.99 54321.00\n"),
		uname:       func() (string, string, error) { return "6.8.0-45-generic", "x86_64", nil },
		hostnamectl: itCat(t, "hostnamectl", " Static hostname: m4b-host\n  Operating System: Ubuntu 24.04.1 LTS\nnot a pair line\n"),
		ip:          itCat(t, "ip_addr", itIPJSON),
	})
}

// ---- CHK-M4-095 (unit half) / CHK-M4-096: exact derivation, raw keys ---------

func TestOSInfoDerivationFromFixtures(t *testing.T) { // CHK-M4-095, -096
	itFixtureHost(t)
	info := itCollect(t)
	want := map[string]string{
		"os_id": "ubuntu", "os_version_id": "24.04", "os_pretty_name": "Ubuntu 24.04.1 LTS",
		"kernel_release": "6.8.0-45-generic", "architecture": "x86_64",
		"memory_mb": "8191", // 8,388,607 kB / 1024 = 8191.999: rounded down
		"uptime_s":  "12345", "cpu_count": strconv.Itoa(len(itCPUSet(t))),
	}
	got := map[string]string{
		"os_id": itStr(info.OsID), "os_version_id": itStr(info.OsVersionID), "os_pretty_name": itStr(info.OsPrettyName),
		"kernel_release": itStr(info.KernelRelease), "architecture": itStr(info.Architecture),
		"memory_mb": itInt(info.MemoryMB), "uptime_s": itInt(info.UptimeS), "cpu_count": itInt(info.CPUCount),
	}
	for k, v := range want {
		if got[k] != v {
			t.Errorf("%s = %s, want %s", k, got[k], v)
		}
	}
	wantIPs := []wire.IPAddress{"127.0.0.1/8", "::1/128", "10.0.0.5/24", "fe80::1/64", "192.0.2.9"}
	if !reflect.DeepEqual(info.IPAddresses, wantIPs) {
		t.Errorf("ip_addresses = %v, want %v (loopback and link-local included, /prefixlen kept, no-local item skipped)", info.IPAddresses, wantIPs)
	}
	keys := make([]string, 0, len(info.Raw))
	for k := range info.Raw {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	if strings.Join(keys, ",") != "errors,hostnamectl,ip_addr,meminfo,os_release" {
		t.Errorf("raw keys = %v, want exactly os_release, hostnamectl, meminfo, ip_addr, errors (#77)", keys)
	}
	if mi, _ := json.Marshal(info.Raw["meminfo"]); string(mi) != `{"MemTotal_kb":8388607}` {
		t.Errorf("raw.meminfo = %s, want {\"MemTotal_kb\":8388607} (not the whole /proc/meminfo)", mi)
	}
	if hc, _ := json.Marshal(info.Raw["hostnamectl"]); string(hc) != `{"Operating System":"Ubuntu 24.04.1 LTS","Static hostname":"m4b-host"}` {
		t.Errorf("raw.hostnamectl = %s", hc)
	}
	osr, _ := info.Raw["os_release"].(map[string]any)
	if len(osr) != 6 || osr["VERSION"] != "24.04.1 LTS (Noble Numbat)" || osr["ID_LIKE"] != "debian" {
		t.Errorf("raw.os_release = %v, want all six pairs", osr)
	}
	if e := itErrs(info); len(e) != 0 {
		t.Errorf("raw.errors = %v, want {}", e)
	}
	itBodyValid(t, info)
	if err := itValidate(t, "OsInfo", info); err != nil {
		t.Fatalf("OsInfo schema: %v", err)
	}
}

func itCPUSet(t *testing.T) []int { // CPUs in this process's affinity mask (nproc's answer)
	t.Helper()
	out, err := exec.Command("nproc").Output() // test oracle, not agent code
	if err != nil {
		t.Fatalf("nproc: %v", err)
	}
	n, err := strconv.Atoi(strings.TrimSpace(string(out)))
	if err != nil {
		t.Fatal(err)
	}
	return make([]int, n)
}

// ---- CHK-M4-095 (APP): the real host, against independent sources -----------

func TestOSInfoMatchesThisHost(t *testing.T) { // CHK-M4-095 (W, W-c), CHK-M4-098 (W-c)
	upBefore := itUptime(t)
	info := itCollect(t)
	upAfter := itUptime(t)
	errs := itErrs(info)

	// os-release: sourced by sh, the format's own reference
	out, err := exec.Command("sh", "-c", `. /etc/os-release; printf '%s\n%s\n%s' "$ID" "$VERSION_ID" "$PRETTY_NAME"`).Output()
	if err != nil {
		t.Fatalf("sh . /etc/os-release: %v", err)
	}
	osv := strings.SplitN(string(out), "\n", 3)
	for i, got := range []*string{info.OsID, info.OsVersionID, info.OsPrettyName} {
		if itStr(got) != osv[i] {
			t.Errorf("os-release field %d = %q, want %q", i, itStr(got), osv[i])
		}
	}
	ur, err := exec.Command("uname", "-r").Output()
	if err != nil {
		t.Fatal(err)
	}
	um, err := exec.Command("uname", "-m").Output()
	if err != nil {
		t.Fatal(err)
	}
	if itStr(info.KernelRelease) != strings.TrimSpace(string(ur)) {
		t.Errorf("kernel_release %q, want uname -r %q", itStr(info.KernelRelease), strings.TrimSpace(string(ur)))
	}
	if itStr(info.Architecture) != strings.TrimSpace(string(um)) {
		t.Errorf("architecture %q, want uname -m %q", itStr(info.Architecture), strings.TrimSpace(string(um)))
	}
	if itStr(info.Architecture) != "x86_64" {
		t.Errorf("architecture %q, want x86_64 (amd64 only)", itStr(info.Architecture))
	}
	if itInt(info.CPUCount) != strconv.Itoa(len(itCPUSet(t))) {
		t.Errorf("cpu_count %s, want nproc %d", itInt(info.CPUCount), len(itCPUSet(t)))
	}
	mi, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		t.Fatal(err)
	}
	var kb int64 = -1
	for _, l := range strings.Split(string(mi), "\n") {
		if f := strings.Fields(l); len(f) == 3 && f[0] == "MemTotal:" {
			kb, _ = strconv.ParseInt(f[1], 10, 64)
		}
	}
	if itInt(info.MemoryMB) != strconv.FormatInt(kb/1024, 10) {
		t.Errorf("memory_mb %s, want %d (MemTotal %d kB / 1024 down)", itInt(info.MemoryMB), kb/1024, kb)
	}
	if info.UptimeS == nil || *info.UptimeS < upBefore || *info.UptimeS > upAfter {
		t.Errorf("uptime_s %s outside [%d, %d]", itInt(info.UptimeS), upBefore, upAfter)
	}
	// ip -j addr parsed by the test
	ipPath := ""
	for _, p := range []string{"/usr/sbin/ip", "/usr/bin/ip", "/sbin/ip", "/bin/ip"} {
		if _, err := os.Stat(p); err == nil {
			ipPath = p
			break
		}
	}
	if ipPath == "" {
		if len(info.IPAddresses) != 0 || errs["ip_addr"] != "not found" || errs["ip_addresses"] != "not found" {
			t.Errorf("no ip binary: ip_addresses %v, errors ip_addr=%v ip_addresses=%v; want [] and \"not found\" (CHK-M4-098)", info.IPAddresses, errs["ip_addr"], errs["ip_addresses"])
		}
		t.Logf("CHK-M4-098: no ip binary on this host: ip_addresses [] with reason %q", errs["ip_addresses"])
	} else {
		ipc := exec.Command("ip", "-j", "addr")
		ipc.Env = []string{"PATH=" + filepath.Dir(ipPath)}
		o, err := ipc.Output()
		if err != nil {
			t.Fatal(err)
		}
		var ifs []struct {
			AddrInfo []struct {
				Local     *string `json:"local"`
				Prefixlen *int    `json:"prefixlen"`
			} `json:"addr_info"`
		}
		if err := json.Unmarshal(o, &ifs); err != nil {
			t.Fatal(err)
		}
		var want []string
		for _, i := range ifs {
			for _, a := range i.AddrInfo {
				if a.Local == nil {
					continue
				}
				s := *a.Local
				if a.Prefixlen != nil {
					s += "/" + strconv.Itoa(*a.Prefixlen)
				}
				want = append(want, s)
			}
		}
		got := make([]string, len(info.IPAddresses))
		for i, a := range info.IPAddresses {
			got[i] = string(a)
		}
		sort.Strings(want)
		sort.Strings(got)
		if strings.Join(got, " ") != strings.Join(want, " ") {
			t.Errorf("ip_addresses %v, want %v", got, want)
		}
		hasLo := false
		for _, a := range got {
			hasLo = hasLo || strings.HasPrefix(a, "127.0.0.1/")
		}
		if !hasLo && strings.Contains(string(o), `"127.0.0.1"`) {
			t.Error("loopback 127.0.0.1 dropped")
		}
	}
	hc := hostnamectlCmd.paths[0]
	if _, err := os.Stat(hc); err != nil {
		if errs["hostnamectl"] != "not found" {
			t.Errorf("no hostnamectl: errors.hostnamectl = %v, want \"not found\" (CHK-M4-098)", errs["hostnamectl"])
		}
	} else if errs["hostnamectl"] == nil {
		if m, _ := info.Raw["hostnamectl"].(map[string]any); len(m) == 0 {
			t.Error("hostnamectl ran but raw.hostnamectl is empty")
		}
	}
	for _, src := range []string{"os_release", "hostnamectl", "meminfo", "ip_addr"} {
		_, inRaw := info.Raw[src]
		_, inErr := errs[src]
		if inRaw == inErr {
			t.Errorf("source %s: in raw %v, in raw.errors %v; want exactly one", src, inRaw, inErr)
		}
	}
	itBodyValid(t, info)
	t.Logf("host os_info: id=%s version=%s pretty=%q kernel=%s arch=%s cpus=%s mem=%s uptime=%s addrs=%d errors=%v",
		itStr(info.OsID), itStr(info.OsVersionID), itStr(info.OsPrettyName), itStr(info.KernelRelease), itStr(info.Architecture),
		itInt(info.CPUCount), itInt(info.MemoryMB), itInt(info.UptimeS), len(info.IPAddresses), errs)
}

func itUptime(t *testing.T) int64 {
	t.Helper()
	b, err := os.ReadFile("/proc/uptime")
	if err != nil {
		t.Fatal(err)
	}
	whole, _, _ := strings.Cut(strings.Fields(string(b))[0], ".")
	n, _ := strconv.ParseInt(whole, 10, 64)
	return n
}

// ---- os-release parsing: same values as sourcing the file with sh -----------

func TestReadOSReleaseAgainstShell(t *testing.T) { // CHK-M4-095 (os-release half)
	cases := []string{
		itOSRelease,
		"ID='debian'\nVERSION_ID='12'\nPRETTY_NAME='Debian GNU/Linux 12 (bookworm)'\n",
		"# comment\n\nID=ubuntu\nVERSION_ID=\"22.04\"\nPRETTY_NAME=\"Ubuntu \\\"22.04\\\" \\$x \\\\ \\`y\\`\"\n",
		"ID=ubuntu\n",
		"PRETTY_NAME=\"a=b=c\"\nID=x\nID=y\n",
		"PRETTY_NAME=\"Ubuntu 24.04 LTS\"",
	}
	for i, c := range cases {
		t.Run(fmt.Sprintf("case_%d", i), func(t *testing.T) {
			p := itFile(t, "os-release", c)
			id, ver, pretty := ReadOSRelease(p)
			sh := exec.Command("sh", "-c", `. "$M4B_OSREL"; printf '%s\n%s\n%s\n%s\n%s\n%s' "${ID+set}" "$ID" "${VERSION_ID+set}" "$VERSION_ID" "${PRETTY_NAME+set}" "$PRETTY_NAME"`)
			sh.Env = []string{"PATH=/usr/bin:/bin", "M4B_OSREL=" + p}
			out, err := sh.Output()
			if err != nil {
				t.Fatalf("sh: %v", err)
			}
			f := strings.SplitN(string(out), "\n", 6)
			for j, got := range []*string{id, ver, pretty} {
				want := "<null>"
				if f[2*j] == "set" {
					want = f[2*j+1]
				}
				if itStr(got) != want {
					t.Errorf("field %d = %q, want %q (as sh sources it)", j, itStr(got), want)
				}
			}
		})
	}
	if a, b, c := ReadOSRelease(filepath.Join(t.TempDir(), "missing")); a != nil || b != nil || c != nil {
		t.Error("missing file: want three nils")
	}
}

// ---- CHK-M4-098: missing or failing sources ---------------------------------

func TestOSInfoMissingAndFailingSources(t *testing.T) { // CHK-M4-098
	missing := filepath.Join(t.TempDir(), "missing")
	none := &command{source: "hostnamectl", paths: []string{missing}, limit: 5 * time.Second, maxOut: 1 << 20}
	noIP := &command{source: "ip_addr", paths: []string{missing, missing + "2"}, args: []string{"-j", "addr"}, limit: 5 * time.Second, maxOut: 1 << 20}
	t.Run("all_missing", func(t *testing.T) {
		itSwap(t, itInputs{osRelease: missing, meminfo: missing, uptime: missing,
			uname:       func() (string, string, error) { return "", "", errors.New("x") },
			hostnamectl: none, ip: noIP})
		info := itCollect(t)
		for _, p := range []*string{info.OsID, info.OsVersionID, info.OsPrettyName, info.KernelRelease, info.Architecture} {
			if p != nil {
				t.Errorf("string field %q, want null", *p)
			}
		}
		if info.MemoryMB != nil || info.UptimeS != nil {
			t.Error("memory_mb / uptime_s not null")
		}
		if info.CPUCount == nil {
			t.Error("cpu_count null (nproc needs no file)")
		}
		want := map[string]string{"os_release": "unreadable", "meminfo": "unreadable", "uptime": "unreadable", "uname": "unreadable",
			"hostnamectl": "not found", "ip_addr": "not found", "ip_addresses": "not found"}
		e := itErrs(info)
		for k, v := range want {
			if e[k] != v {
				t.Errorf("raw.errors[%s] = %v, want %q", k, e[k], v)
			}
		}
		if len(info.IPAddresses) != 0 {
			t.Errorf("ip_addresses %v, want []", info.IPAddresses)
		}
		js, _ := json.Marshal(info)
		if !bytes.Contains(js, []byte(`"ip_addresses":[]`)) {
			t.Errorf("ip_addresses not encoded as []: %s", js)
		}
		itBodyValid(t, info)
	})
	t.Run("failing_and_unparsable", func(t *testing.T) {
		itFixtureHost(t)
		itSwap(t, itInputs{
			meminfo:     itFile(t, "meminfo", "MemTotal: lots kB\n"),
			uptime:      itFile(t, "uptime", "soon\n"),
			hostnamectl: &command{source: "hostnamectl", paths: []string{itScript(t, "echo partial; exit 3")}, limit: 5 * time.Second, maxOut: 1 << 20},
			ip:          itCat(t, "ip_addr", `[{"ifname": "lo", "addr_info": [`),
		})
		info := itCollect(t)
		e := itErrs(info)
		want := map[string]string{"meminfo": "unparsable", "uptime": "unparsable", "hostnamectl": "failed", "ip_addr": "unparsable", "ip_addresses": "unparsable"}
		for k, v := range want {
			if e[k] != v {
				t.Errorf("raw.errors[%s] = %v, want %q", k, e[k], v)
			}
		}
		if _, ok := info.Raw["hostnamectl"]; ok {
			t.Error("raw.hostnamectl kept from a failed command")
		}
		if itStr(info.OsID) != "ubuntu" {
			t.Error("os_id lost although os-release was fine")
		}
		itBodyValid(t, info)
	})
}

// ---- CHK-M4-099: values outside the contract ---------------------------------

func TestOSInfoValuesOutsideContract(t *testing.T) { // CHK-M4-099
	type tc struct {
		name, osrel, kernel, arch, meminfo, uptime, ip string
		check                                          func(t *testing.T, info wire.OsInfo)
	}
	nullWith := func(get func(wire.OsInfo) *string, field string) func(*testing.T, wire.OsInfo) {
		return func(t *testing.T, info wire.OsInfo) {
			if p := get(info); p != nil {
				t.Errorf("%s = %q, want null", field, *p)
			}
			if itErrs(info)[field] != "value outside the contract" {
				t.Errorf("raw.errors[%s] = %v, want \"value outside the contract\"", field, itErrs(info)[field])
			}
		}
	}
	keep := func(get func(wire.OsInfo) *string, field, want string) func(*testing.T, wire.OsInfo) {
		return func(t *testing.T, info wire.OsInfo) {
			if itStr(get(info)) != want {
				t.Errorf("%s = %q, want %q (inside the contract)", field, itStr(get(info)), want)
			}
		}
	}
	pretty := func(o wire.OsInfo) *string { return o.OsPrettyName }
	id := func(o wire.OsInfo) *string { return o.OsID }
	ver := func(o wire.OsInfo) *string { return o.OsVersionID }
	kern := func(o wire.OsInfo) *string { return o.KernelRelease }
	arch := func(o wire.OsInfo) *string { return o.Architecture }
	addrs := func(n int, extra string) string {
		var b strings.Builder
		b.WriteString(`[{"ifname":"eth0","addr_info":[`)
		for i := 0; i < n; i++ {
			if i > 0 {
				b.WriteString(",")
			}
			fmt.Fprintf(&b, `{"local":"10.%d.%d.%d","prefixlen":32}`, i/65536, (i/256)%256, i%256)
		}
		b.WriteString(extra + `]}]`)
		return b.String()
	}
	nest := strings.Repeat("[", 40) + strings.Repeat("]", 40)
	cases := []tc{
		{name: "pretty_128_kept", osrel: "PRETTY_NAME=\"" + strings.Repeat("p", 128) + "\"\n", check: keep(pretty, "os_pretty_name", strings.Repeat("p", 128))},
		{name: "pretty_128_multibyte_kept", osrel: "PRETTY_NAME=\"" + strings.Repeat("é", 128) + "\"\n", check: keep(pretty, "os_pretty_name", strings.Repeat("é", 128))},
		{name: "pretty_129_null", osrel: "PRETTY_NAME=\"" + strings.Repeat("p", 129) + "\"\n", check: nullWith(pretty, "os_pretty_name")},
		{name: "pretty_200_null", osrel: "PRETTY_NAME=\"" + strings.Repeat("p", 200) + "\"\n", check: nullWith(pretty, "os_pretty_name")},
		{name: "id_32_kept", osrel: "ID=" + strings.Repeat("i", 32) + "\n", check: keep(id, "os_id", strings.Repeat("i", 32))},
		{name: "id_33_null", osrel: "ID=" + strings.Repeat("i", 33) + "\n", check: nullWith(id, "os_id")},
		{name: "id_nul_null", osrel: "ID=ub\x00untu\n", check: func(t *testing.T, info wire.OsInfo) {
			nullWith(id, "os_id")(t, info)
			if _, ok := info.Raw["os_release"]; ok {
				t.Error("raw.os_release with a NUL value kept")
			}
			if itErrs(info)["os_release"] != "dropped: outside the contract" {
				t.Errorf("raw.errors.os_release = %v", itErrs(info)["os_release"])
			}
		}},
		{name: "version_16_kept", osrel: "VERSION_ID=" + strings.Repeat("1", 16) + "\n", check: keep(ver, "os_version_id", strings.Repeat("1", 16))},
		{name: "version_17_null", osrel: "VERSION_ID=" + strings.Repeat("1", 17) + "\n", check: nullWith(ver, "os_version_id")},
		{name: "kernel_64_kept", kernel: strings.Repeat("k", 64), check: keep(kern, "kernel_release", strings.Repeat("k", 64))},
		{name: "kernel_65_null", kernel: strings.Repeat("k", 65), check: nullWith(kern, "kernel_release")},
		{name: "arch_17_null", arch: strings.Repeat("a", 17), check: nullWith(arch, "architecture")},
		{name: "memory_2_31_null", meminfo: fmt.Sprintf("MemTotal: %d kB\n", int64(1)<<31*1024), check: func(t *testing.T, info wire.OsInfo) {
			if info.MemoryMB != nil || itErrs(info)["memory_mb"] != "value outside the contract" {
				t.Errorf("memory_mb %s errors %v", itInt(info.MemoryMB), itErrs(info)["memory_mb"])
			}
		}},
		{name: "memory_max_kept", meminfo: fmt.Sprintf("MemTotal: %d kB\n", int64(2147483647)*1024+1023), check: func(t *testing.T, info wire.OsInfo) {
			if itInt(info.MemoryMB) != "2147483647" {
				t.Errorf("memory_mb %s, want 2147483647", itInt(info.MemoryMB))
			}
		}},
		{name: "uptime_2_53_null", uptime: "9007199254740992.5 1\n", check: func(t *testing.T, info wire.OsInfo) {
			if info.UptimeS != nil || itErrs(info)["uptime_s"] != "value outside the contract" {
				t.Errorf("uptime_s %s errors %v", itInt(info.UptimeS), itErrs(info)["uptime_s"])
			}
		}},
		{name: "addresses_256_kept", ip: addrs(256, ""), check: func(t *testing.T, info wire.OsInfo) {
			if len(info.IPAddresses) != 256 || itErrs(info)["ip_addresses"] != nil {
				t.Errorf("%d addresses, errors %v; want all 256", len(info.IPAddresses), itErrs(info)["ip_addresses"])
			}
		}},
		{name: "addresses_257_empty", ip: addrs(257, ""), check: func(t *testing.T, info wire.OsInfo) {
			if len(info.IPAddresses) != 0 || itErrs(info)["ip_addresses"] != "more than 256 addresses" {
				t.Errorf("%d addresses, errors %v; want [] and the reason", len(info.IPAddresses), itErrs(info)["ip_addresses"])
			}
		}},
		{name: "addresses_300_empty", ip: addrs(300, ""), check: func(t *testing.T, info wire.OsInfo) {
			if len(info.IPAddresses) != 0 || itErrs(info)["ip_addresses"] != "more than 256 addresses" {
				t.Errorf("%d addresses, errors %v", len(info.IPAddresses), itErrs(info)["ip_addresses"])
			}
		}},
		{name: "address_bad_empty", ip: addrs(2, `,{"local":"10.0.0.300","prefixlen":24}`), check: func(t *testing.T, info wire.OsInfo) {
			if len(info.IPAddresses) != 0 || itErrs(info)["ip_addresses"] != "value outside the contract" {
				t.Errorf("%v, errors %v", info.IPAddresses, itErrs(info)["ip_addresses"])
			}
		}},
		{name: "raw_too_deep_dropped", ip: nest, check: func(t *testing.T, info wire.OsInfo) {
			if _, ok := info.Raw["ip_addr"]; ok || itErrs(info)["ip_addr"] != "dropped: outside the contract" {
				t.Errorf("raw.ip_addr kept=%v, errors %v", ok, itErrs(info)["ip_addr"])
			}
		}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			itFixtureHost(t)
			in := itInputs{}
			if c.osrel != "" {
				in.osRelease = itFile(t, "os-release", c.osrel)
			}
			if c.kernel != "" || c.arch != "" {
				k, a := c.kernel, c.arch
				if k == "" {
					k = "6.8.0"
				}
				if a == "" {
					a = "x86_64"
				}
				in.uname = func() (string, string, error) { return k, a, nil }
			}
			if c.meminfo != "" {
				in.meminfo = itFile(t, "meminfo", c.meminfo)
			}
			if c.uptime != "" {
				in.uptime = itFile(t, "uptime", c.uptime)
			}
			if c.ip != "" {
				in.ip = itCat(t, "ip_addr", c.ip)
			}
			itSwap(t, in)
			info := itCollect(t)
			c.check(t, info)
			itBodyValid(t, info)
		})
	}
	t.Run("raw_over_256k_dropped_largest", func(t *testing.T) {
		itFixtureHost(t)
		var b strings.Builder
		for i := 0; b.Len() < 300<<10; i++ {
			fmt.Fprintf(&b, "Key%06d: %s\n", i, strings.Repeat("v", 40))
		}
		itSwap(t, itInputs{hostnamectl: itCat(t, "hostnamectl", b.String())})
		info := itCollect(t)
		if _, ok := info.Raw["hostnamectl"]; ok {
			t.Error("raw.hostnamectl (over 256 KiB) kept")
		}
		if itErrs(info)["hostnamectl"] != "dropped: raw over 256 KiB" {
			t.Errorf("raw.errors.hostnamectl = %v", itErrs(info)["hostnamectl"])
		}
		for _, k := range []string{"os_release", "meminfo", "ip_addr"} {
			if _, ok := info.Raw[k]; !ok {
				t.Errorf("raw.%s dropped although only hostnamectl was large", k)
			}
		}
		itBodyValid(t, info)
	})
}

// ---- CHK-M4-097: a hanging command is killed, with its children --------------

func itAlive(pid int) bool {
	b, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		return false
	}
	f := strings.Fields(string(b)[strings.LastIndexByte(string(b), ')')+1:])
	return len(f) > 0 && f[0] != "Z"
}

func TestCommandHangIsKilled(t *testing.T) { // CHK-M4-097
	const limit = time.Second
	for _, c := range []struct {
		name, body string
		bound      time.Duration
	}{
		{"single_process", `echo $$ > "$0.pids"; exec sleep 600`, limit + time.Second},
		{"with_a_child_holding_stdout", `sleep 600 & echo $! > "$0.pids"; echo $$ >> "$0.pids"; exec sleep 600`, limit + waitDelay + time.Second},
		{"child_with_stdout_closed", `sleep 600 >/dev/null 2>&1 & echo $! > "$0.pids"; echo $$ >> "$0.pids"; exec sleep 600`, limit + time.Second},
	} {
		t.Run(c.name, func(t *testing.T) {
			itFixtureHost(t)
			p := itScript(t, c.body)
			itSwap(t, itInputs{hostnamectl: &command{source: "hostnamectl", paths: []string{p}, limit: limit, maxOut: 1 << 20}})
			t0 := time.Now()
			info := itCollect(t)
			el := time.Since(t0)
			if itErrs(info)["hostnamectl"] != "timed out" {
				t.Errorf("raw.errors.hostnamectl = %v, want \"timed out\"", itErrs(info)["hostnamectl"])
			}
			if el > c.bound {
				t.Errorf("collection took %v, bound %v (limit %v)", el, c.bound, limit)
			}
			if itStr(info.OsID) != "ubuntu" || len(info.IPAddresses) == 0 {
				t.Error("other sources lost after the hang")
			}
			time.Sleep(200 * time.Millisecond)
			pids, _ := os.ReadFile(filepath.Clean(p + ".pids"))
			var left []int
			for _, s := range strings.Fields(string(pids)) {
				pid, _ := strconv.Atoi(s)
				if pid > 0 && itAlive(pid) {
					left = append(left, pid)
					_ = syscall.Kill(pid, syscall.SIGKILL)
				}
			}
			if len(left) > 0 {
				t.Errorf("processes of the killed command still running: %v (want the command and its children gone)", left)
			}
		})
	}
}

// ---- CHK-M4-102: output caps -------------------------------------------------

func TestCommandOutputCaps(t *testing.T) { // CHK-M4-102
	const mib = 1 << 20
	for _, c := range []struct {
		name    string
		args    []string
		tooBig  bool
		maxTime time.Duration
	}{
		{"exactly_1MiB", []string{"-c", strconv.Itoa(mib), "/dev/zero"}, false, 5 * time.Second},
		{"1MiB_plus_1", []string{"-c", strconv.Itoa(mib + 1), "/dev/zero"}, true, 5 * time.Second},
		{"2MiB", []string{"-c", strconv.Itoa(2 * mib), "/dev/zero"}, true, 5 * time.Second},
	} {
		t.Run(c.name, func(t *testing.T) {
			cmd := command{source: "hostnamectl", paths: []string{"/usr/bin/head"}, args: c.args, limit: 5 * time.Second, maxOut: mib}
			t0 := time.Now()
			out, err := cmd.run(context.Background())
			if c.tooBig {
				if !errors.Is(err, errTooLarge) || out != nil {
					t.Errorf("err %v, %d bytes; want output too large and no output", err, len(out))
				}
			} else if err != nil || len(out) != mib {
				t.Errorf("err %v, %d bytes; want exactly %d", err, len(out), mib)
			}
			if el := time.Since(t0); el > c.maxTime {
				t.Errorf("took %v", el)
			}
		})
	}
	t.Run("endless_output_killed_at_cap", func(t *testing.T) {
		itFixtureHost(t)
		itSwap(t, itInputs{ip: &command{source: "ip_addr", paths: []string{"/usr/bin/yes"}, limit: 5 * time.Second, maxOut: mib}})
		t0 := time.Now()
		info := itCollect(t)
		if itErrs(info)["ip_addr"] != "output too large" || itErrs(info)["ip_addresses"] != "output too large" || len(info.IPAddresses) != 0 {
			t.Errorf("errors %v, addresses %v", itErrs(info), info.IPAddresses)
		}
		if el := time.Since(t0); el > 3*time.Second {
			t.Errorf("endless output not stopped at the cap: %v", el)
		}
		itBodyValid(t, info)
	})
	if hostnamectlCmd.maxOut != 1<<20 || ipAddrCmd.maxOut != 1<<20 || dpkgQueryCmd.maxOut != 16<<20 {
		t.Errorf("caps %d %d %d, want 1 MiB, 1 MiB, 16 MiB (#35)", hostnamectlCmd.maxOut, ipAddrCmd.maxOut, dpkgQueryCmd.maxOut)
	}
}

// ---- CHK-M4-100: the fixed command list, environment, stdio, no other exec ----

func TestCommandListIsExactly35(t *testing.T) { // CHK-M4-100
	want := []command{
		{source: "hostnamectl", paths: []string{"/usr/bin/hostnamectl"}, limit: 5 * time.Second, maxOut: 1 << 20},
		{source: "ip_addr", paths: []string{"/usr/sbin/ip", "/usr/bin/ip", "/sbin/ip", "/bin/ip"}, args: []string{"-j", "addr"}, limit: 5 * time.Second, maxOut: 1 << 20},
		{source: "dpkg_query", paths: []string{"/usr/bin/dpkg-query"}, args: []string{"-W", `-f=${Package}\t${Version}\t${Architecture}\t${Status}\t${Source}\t${Installed-Size}\n`}, limit: 60 * time.Second, maxOut: 16 << 20},
	}
	for i, got := range []command{hostnamectlCmd, ipAddrCmd, dpkgQueryCmd} {
		w := want[i]
		if got.source != w.source || !reflect.DeepEqual(got.paths, w.paths) || len(got.args) != len(w.args) ||
			(len(w.args) > 0 && !reflect.DeepEqual(got.args, w.args)) || got.limit != w.limit || got.maxOut != w.maxOut {
			t.Errorf("command %d = %+v, want %+v", i, got, w)
		}
	}
	if !reflect.DeepEqual(minimalEnv, []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C"}) {
		t.Errorf("environment %v", minimalEnv)
	}
}

func TestCommandEnvironmentStdinStderrDir(t *testing.T) { // CHK-M4-100 (runtime)
	t.Setenv("M4B_CANARY_ENV", "CANARY-0123456789abcdef")
	t.Setenv("LD_PRELOAD", "/nonexistent/m4b.so")
	run := func(path string, args ...string) string {
		t.Helper()
		out, err := command{source: "hostnamectl", paths: []string{path}, args: args, limit: 5 * time.Second, maxOut: 1 << 20}.run(context.Background())
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		return string(out)
	}
	if env := run("/usr/bin/env"); env != "PATH=/usr/sbin:/usr/bin:/sbin:/bin\nLC_ALL=C\n" {
		t.Errorf("environment of the command:\n%s\nwant exactly PATH and LC_ALL (nothing inherited)", env)
	}
	if s := strings.TrimSpace(run("/usr/bin/readlink", "/proc/self/fd/0")); s != "/dev/null" {
		t.Errorf("stdin is %q, want /dev/null", s)
	}
	if s := strings.TrimSpace(run("/usr/bin/readlink", "/proc/self/fd/2")); s != "/dev/null" {
		t.Errorf("stderr is %q, want /dev/null", s)
	}
	if s := strings.TrimSpace(run("/bin/pwd")); s != "/" {
		t.Errorf("working directory %q, want /", s)
	}
	nf := command{source: "x", paths: []string{"/nonexistent/a", t.TempDir()}, limit: time.Second, maxOut: 10}
	if _, err := nf.run(context.Background()); !errors.Is(err, errNotFound) {
		t.Errorf("no candidate: %v, want not found (a directory is not a program)", err)
	}
	f := itFile(t, "notexec", "#!/bin/sh\necho x\n")
	nx := command{source: "x", paths: []string{f, "/usr/bin/true"}, limit: time.Second, maxOut: 10}
	if _, err := nx.run(context.Background()); err != nil {
		t.Errorf("first candidate not executable, second /usr/bin/true: %v (want the second run)", err)
	}
}

// CHK-M4-100 (static), CHK-M4-344, -345, rewritten as CHK-M10-272 (decisions
// "CHK-M4-100 … is rewritten as CHK-M10-272"; REQ-256, the TASK-211 lint
// allow-list): process execution exists in exactly three non-test files,
// each exactly as allowed, and nowhere else in the agent module:
//   - internal/inventory/command.go: the one exec.CommandContext and the
//     three #35 command literals (M4, unchanged);
//   - internal/runner/spawn_linux.go: the plugin start, one exec.Cmd struct
//     literal, the "/bin/sh" and "-c" literals once each, no exec.Command*;
//   - internal/capread/serve_linux.go: one exec.CommandContext over the
//     fixed table, no shell literal.
func TestNoOtherProcessExecutionInAgent(t *testing.T) {
	const (
		invCmd   = "internal/inventory/command.go"
		spawn    = "internal/runner/spawn_linux.go"
		capServe = "internal/capread/serve_linux.go"
	)
	root := itModuleRoot(t)
	fset := token.NewFileSet()
	calls := map[string]map[string]int{} // file -> call -> count
	structLits := map[string]int{}       // exec.Cmd composite literals per file
	shellLits := map[string]map[string]int{}
	var cmdLits []string
	execImports := map[string]bool{}
	err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		f, err := parser.ParseFile(fset, path, nil, 0)
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(root, path)
		rel = filepath.ToSlash(rel)
		for _, im := range f.Imports {
			if p, _ := strconv.Unquote(im.Path.Value); p == "os/exec" {
				execImports[rel] = true
			}
		}
		ast.Inspect(f, func(n ast.Node) bool {
			switch x := n.(type) {
			case *ast.CallExpr:
				if sel, ok := x.Fun.(*ast.SelectorExpr); ok {
					if id, ok := sel.X.(*ast.Ident); ok {
						name := id.Name + "." + sel.Sel.Name
						switch name {
						case "exec.Command", "exec.CommandContext", "os.StartProcess", "syscall.Exec", "syscall.ForkExec",
							"syscall.StartProcess", "unix.Exec", "exec.LookPath":
							if calls[rel] == nil {
								calls[rel] = map[string]int{}
							}
							calls[rel][name]++
						}
					}
				}
			case *ast.BasicLit:
				if x.Kind == token.STRING {
					if v, err := strconv.Unquote(x.Value); err == nil {
						switch v {
						case "sh", "bash", "/bin/sh", "/bin/bash", "/usr/bin/sh", "/usr/bin/bash", "dash", "-c":
							if shellLits[rel] == nil {
								shellLits[rel] = map[string]int{}
							}
							shellLits[rel][v]++
						}
					}
				}
			case *ast.CompositeLit:
				if id, ok := x.Type.(*ast.Ident); ok && id.Name == "command" {
					cmdLits = append(cmdLits, rel)
				}
				if sel, ok := x.Type.(*ast.SelectorExpr); ok {
					if id, ok := sel.X.(*ast.Ident); ok && id.Name == "exec" && sel.Sel.Name == "Cmd" {
						structLits[rel]++
					}
				}
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	wantCalls := map[string]map[string]int{invCmd: {"exec.CommandContext": 1}, capServe: {"exec.CommandContext": 1}}
	if fmt.Sprint(calls) != fmt.Sprint(wantCalls) {
		t.Errorf("process execution calls %v; want exactly %v", calls, wantCalls)
	}
	if fmt.Sprint(structLits) != fmt.Sprint(map[string]int{spawn: 1}) {
		t.Errorf("exec.Cmd literals %v; want exactly one, in %s", structLits, spawn)
	}
	// the command runner's own files, the plugin start and the capread
	// helper may import os/exec; nothing else may
	for f := range execImports {
		allowed := f == invCmd || f == spawn || f == capServe ||
			(strings.HasPrefix(f, "internal/inventory/command_") && strings.Count(f, "/") == 2)
		if !allowed {
			t.Errorf("os/exec imported by %s; want only %s, %s, %s and internal/inventory/command_*.go", f, invCmd, spawn, capServe)
		}
	}
	if !execImports[invCmd] || !execImports[spawn] || !execImports[capServe] {
		t.Errorf("os/exec imports %v: an allowed site no longer imports it; the static check is out of date", execImports)
	}
	if fmt.Sprint(shellLits) != fmt.Sprint(map[string]map[string]int{spawn: {"-c": 1, "/bin/sh": 1}}) {
		t.Errorf("shell names or -c in non-test code: %v; want exactly \"/bin/sh\" and \"-c\" once each in %s", shellLits, spawn)
	}
	if len(cmdLits) != 3 {
		t.Errorf("command literals in %v; want exactly the three #35 entries in command.go", cmdLits)
	}
	for _, f := range cmdLits {
		if f != invCmd {
			t.Errorf("a command value is built outside command.go: %s", f)
		}
	}
}

// ---- CHK-M4-101: the collection takes no job, heartbeat or manager value -----

func TestCollectionTakesNoExternalInput(t *testing.T) { // CHK-M4-101
	ctxT := reflect.TypeOf((*context.Context)(nil)).Elem()
	for name, f := range map[string]any{"CollectOSInfo": CollectOSInfo, "CollectBody": CollectBody, "ListPackages": ListPackages} {
		ft := reflect.TypeOf(f)
		if ft.NumIn() != 1 || ft.In(0) != ctxT {
			t.Errorf("%s takes %v; want only a context.Context", name, ft)
		}
	}
	if ft := reflect.TypeOf(ReadOSRelease); ft.NumIn() != 1 || ft.In(0).Kind() != reflect.String {
		t.Errorf("ReadOSRelease %v", ft)
	}
}
