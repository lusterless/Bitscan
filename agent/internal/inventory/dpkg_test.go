//go:build linux

package inventory

// TP-M4-10 (TASK-095; REQ-100, REQ-101; TS §3.4 L235, §6.5 L1186; #33, #72,
// #77 (d); lead rulings 2026-10-24 TASK-094/095 Q2-Q5). Expected values:
// one item per 6-field line, rows exactly as printed (duplicates kept), empty
// Source and Installed-Size null, non-integer sizes null and counted, lines
// without 6 fields skipped and counted; list_sha256 = lowercase hex SHA-256
// of the sorted-by-bytes UTF-8 lines name\tversion\tarchitecture\tstatus\n,
// checked against the manager's own loader.list_sha256 (Python) as oracle;
// body = compact JSON, gzip, valid against InventoryBody.

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/wire"
)

func itPtr[T any](v T) *T { return &v }

// itOracle hashes package lists with the manager's loader.list_sha256 (the
// TS §6.5 oracle shared by the contract fixtures). Lists go in as JSON on stdin.
func itOracle(t *testing.T, lists [][]wire.PackageItem) []string {
	t.Helper()
	contract := filepath.Join(filepath.Dir(itModuleRoot(t)), "manager", "tests", "contract")
	if _, err := os.Stat(filepath.Join(contract, "loader.py")); err != nil {
		t.Fatalf("manager/tests/contract/loader.py: %v", err)
	}
	in, err := json.Marshal(lists)
	if err != nil {
		t.Fatal(err)
	}
	py := exec.Command("python3", "-I", "-c", `import json, os, sys
sys.path.insert(0, os.environ["M4B_CONTRACT"])
import loader
for pk in json.load(sys.stdin):
    print(loader.list_sha256(pk))`)
	py.Env = []string{"PATH=/usr/bin:/bin", "M4B_CONTRACT=" + contract}
	py.Stdin = bytes.NewReader(in)
	out, err := py.Output()
	if err != nil {
		t.Fatalf("python3 oracle: %v", err)
	}
	return strings.Fields(string(out))
}

func itGunzip(t *testing.T, gz []byte) []byte {
	t.Helper()
	if len(gz) < 2 || gz[0] != 0x1f || gz[1] != 0x8b {
		t.Fatalf("body is not gzip (first bytes %x)", gz[:min(4, len(gz))])
	}
	zr, err := gzip.NewReader(bytes.NewReader(gz))
	if err != nil {
		t.Fatal(err)
	}
	out, err := io.ReadAll(zr)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// ---- CHK-M4-110 (APP): the real dpkg-query of this host ----------------------

func TestDpkgRealHostList(t *testing.T) { // CHK-M4-110 (W, W-c)
	pk, err := ListPackages(context.Background())
	if err != nil {
		t.Fatalf("ListPackages: %v", err)
	}
	// the test's own dpkg-query runs with the TS §3.4 format and the plain -W
	q := exec.Command("dpkg-query", "-W", `-f=${Package}\t${Version}\t${Architecture}\t${Status}\t${Source}\t${Installed-Size}\n`)
	q.Env = []string{"PATH=/usr/bin:/bin", "LC_ALL=C"}
	raw, err := q.Output()
	if err != nil {
		t.Fatal(err)
	}
	plain := exec.Command("dpkg-query", "-W")
	plain.Env = q.Env
	pw, err := plain.Output()
	if err != nil {
		t.Fatal(err)
	}
	n := strings.Count(string(pw), "\n")
	if len(pk.Items) != n || pk.BadLines != 0 {
		t.Fatalf("%d items, %d bad lines; dpkg-query -W | wc -l = %d", len(pk.Items), pk.BadLines, n)
	}
	lines := strings.Split(strings.TrimSuffix(string(raw), "\n"), "\n")
	if len(lines) != len(pk.Items) {
		t.Fatalf("%d lines from the test's dpkg-query, %d items", len(lines), len(pk.Items))
	}
	nullSrc, nullSize := 0, 0
	for i, l := range lines {
		f := strings.Split(l, "\t")
		it := pk.Items[i]
		if it.Name != f[0] || it.Version != f[1] || it.Architecture != f[2] || it.Status != f[3] {
			t.Fatalf("line %d %q -> %+v", i, l, it)
		}
		if f[4] == "" {
			nullSrc++
			if it.Source != nil {
				t.Fatalf("line %d: empty Source sent as %q, want null", i, *it.Source)
			}
		} else if it.Source == nil || *it.Source != f[4] {
			t.Fatalf("line %d: Source %v, want %q", i, it.Source, f[4])
		}
		if f[5] == "" {
			nullSize++
			if it.InstalledSizeKB != nil {
				t.Fatalf("line %d: empty Installed-Size sent as %d", i, *it.InstalledSizeKB)
			}
		} else if n, _ := strconv.ParseInt(f[5], 10, 64); it.InstalledSizeKB == nil || *it.InstalledSizeKB != n {
			t.Fatalf("line %d: Installed-Size %v, want %s", i, it.InstalledSizeKB, f[5])
		}
	}
	if got, want := ListSHA256(pk.Items), itOracle(t, [][]wire.PackageItem{pk.Items})[0]; string(got) != want {
		t.Fatalf("list_sha256 %s, manager oracle %s", got, want)
	}
	t.Logf("dpkg-query: %d packages, %d with empty Source, %d with empty Installed-Size, list_sha256 %s",
		len(pk.Items), nullSrc, nullSize, ListSHA256(pk.Items))
}

// ---- CHK-M4-111: edge lines ---------------------------------------------------

func TestDpkgParseEdgeLines(t *testing.T) { // CHK-M4-111
	l := func(f ...string) string { return strings.Join(f, "\t") }
	good := l("apt", "2.7.14", "amd64", "install ok installed", "", "4096")
	cases := []struct {
		name               string
		in                 string
		items              []wire.PackageItem
		badLines, badSizes int
	}{
		{"empty_input", "", []wire.PackageItem{}, 0, 0},
		{"one_row", good + "\n", []wire.PackageItem{{Name: "apt", Version: "2.7.14", Architecture: "amd64", Status: "install ok installed", InstalledSizeKB: itPtr(int64(4096))}}, 0, 0},
		{"no_final_newline", good, []wire.PackageItem{{Name: "apt", Version: "2.7.14", Architecture: "amd64", Status: "install ok installed", InstalledSizeKB: itPtr(int64(4096))}}, 0, 0},
		{"five_and_seven_fields_skipped", l("a", "1", "amd64", "install ok installed", "") + "\n" + good + "\n" + l("b", "1", "amd64", "install ok installed", "", "1", "x") + "\n",
			[]wire.PackageItem{{Name: "apt", Version: "2.7.14", Architecture: "amd64", Status: "install ok installed", InstalledSizeKB: itPtr(int64(4096))}}, 2, 0},
		{"blank_line_in_middle", good + "\n\n" + good + "\n", nil, 1, 0},
		{"source_with_version_kept", l("libc6", "2.39-0ubuntu8", "amd64", "install ok installed", "glibc (2.39-0ubuntu8.3)", "13000") + "\n",
			[]wire.PackageItem{{Name: "libc6", Version: "2.39-0ubuntu8", Architecture: "amd64", Status: "install ok installed", Source: itPtr("glibc (2.39-0ubuntu8.3)"), InstalledSizeKB: itPtr(int64(13000))}}, 0, 0},
		{"sizes", strings.Join([]string{
			l("s1", "1", "all", "install ok installed", "", "12a"),
			l("s2", "1", "all", "install ok installed", "", "+5"),
			l("s3", "1", "all", "install ok installed", "", "-5"),
			l("s4", "1", "all", "install ok installed", "", " 5"),
			l("s5", "1", "all", "install ok installed", "", "007"),
			l("s6", "1", "all", "install ok installed", "", "2147483648"),
			l("s7", "1", "all", "install ok installed", "", "99999999999999999999"),
			l("s8", "1", "all", "install ok installed", "", "0"),
		}, "\n") + "\n", []wire.PackageItem{
			{Name: "s1", Version: "1", Architecture: "all", Status: "install ok installed"},
			{Name: "s2", Version: "1", Architecture: "all", Status: "install ok installed"},
			{Name: "s3", Version: "1", Architecture: "all", Status: "install ok installed"},
			{Name: "s4", Version: "1", Architecture: "all", Status: "install ok installed"},
			{Name: "s5", Version: "1", Architecture: "all", Status: "install ok installed", InstalledSizeKB: itPtr(int64(7))},
			{Name: "s6", Version: "1", Architecture: "all", Status: "install ok installed", InstalledSizeKB: itPtr(int64(2147483648))},
			{Name: "s7", Version: "1", Architecture: "all", Status: "install ok installed"},
			{Name: "s8", Version: "1", Architecture: "all", Status: "install ok installed", InstalledSizeKB: itPtr(int64(0))},
		}, 0, 5},
		{"non_ascii_kept", l("libé", "1.0~ß", "amd64", "install ok installed", "src-ü", "") + "\n",
			[]wire.PackageItem{{Name: "libé", Version: "1.0~ß", Architecture: "amd64", Status: "install ok installed", Source: itPtr("src-ü")}}, 0, 0},
		{"invalid_utf8_one_replacement_per_byte", l("a\xff\xfeb", "1", "amd64", "install ok installed", "", "") + "\n",
			[]wire.PackageItem{{Name: "a��b", Version: "1", Architecture: "amd64", Status: "install ok installed"}}, 0, 0},
		{"crlf_line", l("crlf", "1", "amd64", "install ok installed", "", "5") + "\r\n",
			[]wire.PackageItem{{Name: "crlf", Version: "1", Architecture: "amd64", Status: "install ok installed"}}, 0, 1},
		{"duplicates_kept", good + "\n" + good + "\n", nil, 0, 0},
		{"status_not_installed_kept", l("old", "1", "amd64", "deinstall ok config-files", "", "") + "\n",
			[]wire.PackageItem{{Name: "old", Version: "1", Architecture: "amd64", Status: "deinstall ok config-files"}}, 0, 0},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			p := ParseDpkg([]byte(c.in))
			if p.Items == nil {
				t.Fatal("Items nil (would encode as null)")
			}
			if p.BadLines != c.badLines || p.BadSizes != c.badSizes {
				t.Errorf("BadLines %d BadSizes %d, want %d %d", p.BadLines, p.BadSizes, c.badLines, c.badSizes)
			}
			switch c.name {
			case "blank_line_in_middle", "duplicates_kept":
				if len(p.Items) != 2 || !reflect.DeepEqual(p.Items[0], p.Items[1]) {
					t.Errorf("items %+v, want the row twice (rows sent exactly as printed)", p.Items)
				}
			default:
				if !reflect.DeepEqual(p.Items, c.items) {
					t.Errorf("items\n %s\nwant\n %s", itJSON(p.Items), itJSON(c.items))
				}
			}
		})
	}
}

func itJSON(v any) string { b, _ := json.Marshal(v); return string(b) }

// ---- CHK-M4-112: list_sha256 against the manager -----------------------------

func TestListSHA256MatchesManager(t *testing.T) { // CHK-M4-112, CHK-M4-350
	if got := ListSHA256(nil); got != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" {
		t.Errorf("empty list hash %s", got)
	}
	p := func(name, ver, arch, status string) wire.PackageItem {
		return wire.PackageItem{Name: name, Version: ver, Architecture: arch, Status: status}
	}
	one := p("apt", "2.7.14", "amd64", "install ok installed")
	single := sha256.Sum256([]byte("apt\t2.7.14\tamd64\tinstall ok installed\n"))
	if got := ListSHA256([]wire.PackageItem{one}); string(got) != hex.EncodeToString(single[:]) {
		t.Errorf("one package: %s, want sha256 of the single line with its final \\n", got)
	}
	withSrc := one
	withSrc.Source, withSrc.InstalledSizeKB = itPtr("apt-src"), itPtr(int64(9))
	if ListSHA256([]wire.PackageItem{withSrc}) != ListSHA256([]wire.PackageItem{one}) {
		t.Error("source or installed size changes list_sha256 (only name, version, architecture, status are hashed)")
	}
	lists := [][]wire.PackageItem{
		{p("apt", "1", "amd64", "install ok installed"), p("Zz", "1", "amd64", "install ok installed")},           // bytes: Z < a
		{p("zlib1g", "1", "amd64", "i"), p("é", "1", "amd64", "i"), p("e", "1", "amd64", "i")},                    // é (0xc3) after z
		{p("libc6", "2.39", "i386", "install ok installed"), p("libc6", "2.39", "amd64", "install ok installed")}, // multi-arch
		{p("a", "1", "amd64", "x"), p("a", "1", "amd64", "x")},                                                    // duplicate rows
		{p("a-b", "1", "all", "i"), p("a.b", "1", "all", "i"), p("a_b", "1", "all", "i"), p("a+b", "1", "all", "i"), p("A", "1", "all", "i")},
		{p("pkg�", "1", "amd64", "i"), p("pkg", "1:2.0~rc1+dfsg-3ubuntu0.1", "amd64", "deinstall ok config-files")},
		{p("a", "1", "amd64", "i"), p("a", "1", "amd64", "i "), p("a", "10", "amd64", "i"), p("a", "1 ", "amd64", "i")},
	}
	oracle := itOracle(t, lists)
	for i, l := range lists {
		if got := ListSHA256(l); string(got) != oracle[i] {
			t.Errorf("list %d: Go %s, manager %s", i, got, oracle[i])
		}
		rev := make([]wire.PackageItem, len(l))
		for j := range l {
			rev[j] = l[len(l)-1-j]
		}
		if ListSHA256(rev) != ListSHA256(l) {
			t.Errorf("list %d: hash depends on input order", i)
		}
	}
	// every valid inventory fixture of the shared contract set
	root := filepath.Dir(itModuleRoot(t))
	fdir := filepath.Join(root, "manager", "tests", "contract", "fixtures")
	mb, err := os.ReadFile(filepath.Clean(filepath.Join(fdir, "manifest.json")))
	if err != nil {
		t.Fatal(err)
	}
	var man struct {
		Fixtures []struct {
			File, Route, Direction string
			Valid                  bool
			Decoder                *struct{ Reason string }
			Generate               *struct {
				Op    string
				Count int
			}
		}
	}
	if err := json.Unmarshal(mb, &man); err != nil {
		t.Fatal(err)
	}
	checked := 0
	for _, f := range man.Fixtures {
		if f.Route != "inventory" || f.Direction != "request" || !f.Valid {
			continue
		}
		data, err := os.ReadFile(filepath.Clean(filepath.Join(fdir, filepath.FromSlash(f.File))))
		if err != nil {
			t.Fatal(err)
		}
		var body struct {
			Packages   []wire.PackageItem `json:"packages"`
			ListSHA256 string             `json:"list_sha256"`
		}
		if err := json.Unmarshal(data, &body); err != nil {
			t.Fatal(err)
		}
		if f.Generate != nil && f.Generate.Op == "packages_count" {
			continue // generated below through the loader
		}
		got := string(ListSHA256(body.Packages))
		if f.Decoder != nil && f.Decoder.Reason == "list_sha256 mismatch" {
			if got == body.ListSHA256 {
				t.Errorf("%s: Go hash equals the deliberately wrong fixture hash", f.File)
			}
			if o := itOracle(t, [][]wire.PackageItem{body.Packages})[0]; got != o {
				t.Errorf("%s: Go %s, manager %s", f.File, got, o)
			}
		} else if got != body.ListSHA256 {
			t.Errorf("%s: Go %s, fixture %s", f.File, got, body.ListSHA256)
		}
		checked++
	}
	// the generated 50,000-package fixture, built by the manager's loader
	contract := filepath.Join(root, "manager", "tests", "contract")
	py := exec.Command("python3", "-I", "-c", `import json, os, sys
sys.path.insert(0, os.environ["M4B_CONTRACT"])
import loader
m = loader.manifest()
e = [f for f in m["fixtures"] if f["file"] == "inventory/request_valid_packages_50000.json"][0]
base = json.load(open(os.path.join(os.environ["M4B_CONTRACT"], "fixtures", e["file"])))
b = loader.apply_generate(base, e["generate"])
json.dump({"packages": b["packages"], "list_sha256": b["list_sha256"]}, sys.stdout)`)
	py.Env = []string{"PATH=/usr/bin:/bin", "M4B_CONTRACT=" + contract}
	out, err := py.Output()
	if err != nil {
		t.Fatalf("loader generate: %v", err)
	}
	var gen struct {
		Packages   []wire.PackageItem `json:"packages"`
		ListSHA256 string             `json:"list_sha256"`
	}
	if err := json.Unmarshal(out, &gen); err != nil {
		t.Fatal(err)
	}
	if len(gen.Packages) != 50000 || string(ListSHA256(gen.Packages)) != gen.ListSHA256 {
		t.Errorf("generated 50,000: %d packages, Go %s, loader %s", len(gen.Packages), ListSHA256(gen.Packages), gen.ListSHA256)
	}
	t.Logf("%d fixture bodies and the generated 50,000-package body match the manager", checked)
}

// ---- CHK-M4-113: the body ---------------------------------------------------------

func itInfo() wire.OsInfo {
	return wire.OsInfo{OsID: itPtr("ubuntu"), OsVersionID: itPtr("24.04"), OsPrettyName: itPtr("Ubuntu <b>&</b> 24.04"),
		KernelRelease: itPtr("6.8.0"), Architecture: itPtr("x86_64"), CPUCount: itPtr(int64(4)), MemoryMB: itPtr(int64(7962)),
		IPAddresses: []wire.IPAddress{"10.0.0.5/24", "fe80::1/64"}, UptimeS: itPtr(int64(86400)),
		Raw: map[string]any{"os_release": map[string]any{"ID": "ubuntu"}, "errors": map[string]any{"uname": "unreadable"}}}
}

func TestBuildBodyRoundTrip(t *testing.T) { // CHK-M4-113
	l := func(f ...string) string { return strings.Join(f, "\t") }
	out := strings.Join([]string{
		l("zlib1g", "1:1.3", "amd64", "install ok installed", "zlib", "164"),
		l("libc6", "2.39", "amd64", "install ok installed", "glibc", ""),
		l("libc6", "2.39", "i386", "install ok installed", "glibc", "12000"),
		l("libc6", "2.39", "i386", "install ok installed", "glibc", "12000"), // duplicate row: sent as printed
		l("libé<b>", "1", "all", "deinstall ok config-files", "", "x"),
		l("bad", "line", "CANARY-badline0000000"),
	}, "\n") + "\n"
	pk := ParseDpkg([]byte(out))
	info := itInfo()
	origErrs := itJSON(info.Raw)
	gz, err := BuildBody(info, pk)
	if err != nil {
		t.Fatalf("BuildBody: %v", err)
	}
	if itJSON(info.Raw) != origErrs {
		t.Errorf("BuildBody changed the caller's raw map: %s", itJSON(info.Raw))
	}
	js := itGunzip(t, gz)
	if bytes.HasSuffix(js, []byte("\n")) {
		t.Error("body ends with a newline")
	}
	var compact bytes.Buffer
	if err := json.Compact(&compact, js); err != nil || !bytes.Equal(compact.Bytes(), js) {
		t.Error("body is not compact JSON")
	}
	if i := bytes.Index(js, []byte(`\u00`)); !bytes.Contains(js, []byte("<b>&</b>")) || i >= 0 {
		lo := max(0, i-60)
		t.Errorf("HTML escaping applied (want the text as is); raw <b>&</b> present: %v; first escape at %d: %q",
			bytes.Contains(js, []byte("<b>&</b>")), i, js[lo:min(len(js), lo+120)])
	}
	if bytes.Contains(js, []byte("CANARY-badline")) {
		t.Error("the content of a skipped line reached the body")
	}
	inst := map[string]any{}
	if err := json.Unmarshal(js, &inst); err != nil {
		t.Fatal(err)
	}
	if err := itValidate(t, "InventoryBody", inst); err != nil {
		t.Fatalf("body does not validate against InventoryBody: %v", err)
	}
	var back wire.InventoryBody
	if err := wire.DecodeStrict(js, &back); err != nil {
		t.Fatalf("DecodeStrict: %v", err)
	}
	if !reflect.DeepEqual(back.Packages, pk.Items) || len(back.Packages) != 5 {
		t.Errorf("packages after the round trip:\n %s\nwant\n %s", itJSON(back.Packages), itJSON(pk.Items))
	}
	if string(back.ListSHA256) != itOracle(t, [][]wire.PackageItem{back.Packages})[0] {
		t.Errorf("list_sha256 %s does not match the manager's hash of the sent packages", back.ListSHA256)
	}
	errs, _ := back.OsInfo.Raw["errors"].(map[string]any)
	if errs["dpkg_query"] != "1 lines not in the 6-field format" || errs["installed_size_kb"] != "1 values not a decimal integer" || errs["uname"] != "unreadable" {
		t.Errorf("raw.errors %v", errs)
	}
	if itStr(back.OsInfo.OsPrettyName) != "Ubuntu <b>&</b> 24.04" || len(back.OsInfo.IPAddresses) != 2 {
		t.Errorf("os_info changed: %s", itJSON(back.OsInfo))
	}
	// nil list → "packages":[]
	gz2, err := BuildBody(itInfo(), Packages{})
	if err != nil {
		t.Fatal(err)
	}
	js2 := itGunzip(t, gz2)
	if !bytes.Contains(js2, []byte(`"packages":[]`)) || !bytes.Contains(js2, []byte(`"list_sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"`)) {
		t.Errorf("empty list body: %s", js2)
	}
	// an os_info outside the contract is refused (no upload), never sent
	bad := itInfo()
	bad.OsID = itPtr(strings.Repeat("x", 33))
	if _, err := BuildBody(bad, pk); err == nil {
		t.Error("BuildBody sent an os_info outside the contract")
	}
}

// ---- CHK-M4-114: 50,000 and 50,001 rows -----------------------------------------

func TestBuildBodyLargeLists(t *testing.T) { // CHK-M4-114
	mk := func(n int) []byte {
		var b strings.Builder
		for i := 0; i < n; i++ {
			fmt.Fprintf(&b, "pkg-%05d\t1.%d.0-1ubuntu0.24.04.1\tamd64\tinstall ok installed\tsrc-%d\t%d\n", i, i%97, i%3000, 100+i%5000)
		}
		return []byte(b.String())
	}
	for _, n := range []int{50000, 50001} {
		t.Run(strconv.Itoa(n), func(t *testing.T) {
			pk := ParseDpkg(mk(n))
			t0 := time.Now()
			gz, err := BuildBody(itInfo(), pk)
			el := time.Since(t0)
			if err != nil {
				t.Fatal(err)
			}
			if n == 50000 && el > 5*time.Second {
				t.Errorf("50,000 rows built in %v, want < 5 s", el)
			}
			if len(gz) >= 10485760 {
				t.Errorf("gzip body %d bytes, want < 10,485,760", len(gz))
			}
			var back wire.InventoryBody
			js := itGunzip(t, gz)
			if err := json.Unmarshal(js, &back); err != nil {
				t.Fatal(err)
			}
			if len(back.Packages) != n {
				t.Fatalf("%d packages in the body, want %d (no silent truncation)", len(back.Packages), n)
			}
			inst := map[string]any{}
			_ = json.Unmarshal(js, &inst)
			verr := itValidate(t, "InventoryBody", inst)
			if n == 50000 && verr != nil {
				t.Errorf("50,000 rows: %v", verr)
			}
			if n == 50001 && verr == nil {
				t.Error("50,001 rows validated (want the manager to refuse it: 422)")
			}
			t.Logf("%d rows: built in %v, gzip %d bytes, JSON %d bytes", n, el, len(gz), len(js))
		})
	}
}
