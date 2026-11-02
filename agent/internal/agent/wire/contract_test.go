// Go half of the shared agent wire-contract test (TS §8.3 Contract, REQ-091,
// gate G35; tests/m4/test-plan.md TP-M4-01, CHK-M4-010 to -019).
//
// Expected values come from the shared fixtures in
// manager/tests/contract/fixtures/ (written from TS §6.5 and the #60 field
// table, not from this package) and from the component schemas in
// manager/openapi.json. The fixtures are read in place, never copied.
// Rulings (work/decisions.md 2026-10-24): `lone surrogate` schema gaps assert
// nothing (skipped by name); `nan_inf` gaps must be refused; the three
// schema-valid fixtures the manager decoder refuses decode and re-encode like
// any valid fixture.
package wire_test

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"maps"
	"math/big"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"bitscan.local/agent/internal/agent/wire"
)

var (
	repoRoot     = filepath.Join("..", "..", "..", "..")
	fixturesDir  = filepath.Join(repoRoot, "manager", "tests", "contract", "fixtures")
	openapiPath  = filepath.Join(repoRoot, "manager", "openapi.json")
	uuidPattern  = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
	timeTextLike = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt]`)
)

// Number of entries in manifest.json when this test was written (TP-M3-01).
const manifestEntries = 276

type modelRef struct {
	Model string `json:"model"`
}

type manifestRoute struct {
	Method   string    `json:"method"`
	Path     string    `json:"path"`
	Request  *modelRef `json:"request"`
	Response *modelRef `json:"response"`
}

type fixture struct {
	File      string          `json:"file"`
	Route     string          `json:"route"`
	Direction string          `json:"direction"`
	Valid     bool            `json:"valid"`
	Class     string          `json:"class"`
	Reason    string          `json:"reason"`
	Decoder   json.RawMessage `json:"decoder"`
	Generate  *generateOp     `json:"generate"`
	SchemaGap string          `json:"schema_gap"`
}

type generateOp struct {
	Op    string `json:"op"`
	Count int    `json:"count"`
	Bytes int    `json:"bytes"`
}

type manifestDoc struct {
	FakeToken              string                   `json:"fake_token"`
	Routes                 map[string]manifestRoute `json:"routes"`
	RequiredInvalidClasses map[string][]string      `json:"required_invalid_classes"`
	Fixtures               []fixture                `json:"fixtures"`
	SchemaGaps             map[string]string        `json:"schema_gaps"`
	SharedFiles            []struct {
		File string `json:"file"`
	} `json:"shared_files"`
}

func (f fixture) key() string { return f.Route + "/" + f.Direction }

func (f fixture) name() string { return strings.TrimSuffix(f.File, ".json") }

// decoders maps each body to the Go type the agent uses for it.
var decoders = map[string]func([]byte) (any, error){
	"enrol/request":      decodeAs[wire.EnrolRequest],
	"enrol/response":     decodeAs[wire.EnrolResponse],
	"heartbeat/request":  decodeAs[wire.HeartbeatRequest],
	"heartbeat/response": decodeAs[wire.HeartbeatResponse],
	"jobs/response":      decodeAs[wire.JobsResponse],
	"results/request":    decodeAs[wire.ResultsRequest],
	"results/response":   decodeAs[wire.ResultsResponse],
	"inventory/request":  decodeAs[wire.InventoryBody],
	"rotate/request":     decodeAs[wire.RotateRequest],
	"rotate/response":    decodeAs[wire.RotateResponse],
}

func decodeAs[T any](b []byte) (any, error) {
	var v T
	if err := wire.DecodeStrict(b, &v); err != nil {
		return nil, err
	}
	return &v, nil
}

var (
	loadOnce  sync.Once
	loadedDoc manifestDoc
	loadErr   error
)

func loadManifest(t *testing.T) manifestDoc {
	t.Helper()
	loadOnce.Do(func() {
		var raw []byte
		raw, loadErr = os.ReadFile(filepath.Clean(filepath.Join(fixturesDir, "manifest.json")))
		if loadErr == nil {
			loadErr = json.Unmarshal(raw, &loadedDoc)
		}
	})
	if loadErr != nil {
		t.Fatalf("shared fixtures not readable (the contract test needs the manager tree): %v", loadErr)
	}
	return loadedDoc
}

// ---- generate ops (the manifest "about" text; mirrors manager/tests/contract/loader.py)

func uuidFor(n int) string {
	h := fmt.Sprintf("%032x", n)
	return h[:8] + "-" + h[8:12] + "-4" + h[13:16] + "-8" + h[17:20] + "-" + h[20:32]
}

// oracleListSHA256 is this test's own TS §6.5 L1186 oracle: the lines
// name\tversion\tarchitecture\tstatus\n in UTF-8, sorted by bytes,
// concatenated, SHA-256, lowercase hex.
func oracleListSHA256(pkgs []map[string]any) string {
	lines := make([][]byte, 0, len(pkgs))
	for _, p := range pkgs {
		lines = append(lines, []byte(fmt.Sprintf("%s\t%s\t%s\t%s\n", p["name"], p["version"], p["architecture"], p["status"])))
	}
	sort.Slice(lines, func(i, j int) bool { return bytes.Compare(lines[i], lines[j]) < 0 })
	sum := sha256.Sum256(bytes.Join(lines, nil))
	return hex.EncodeToString(sum[:])
}

func parseNumbers(b []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return v, nil
}

func compactLen(v any) int {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return len(b)
}

// fixtureBody returns the bytes a client would send for f.
func fixtureBody(t *testing.T, f fixture) []byte {
	t.Helper()
	raw, err := os.ReadFile(filepath.Clean(filepath.Join(fixturesDir, filepath.FromSlash(f.File))))
	if err != nil {
		t.Fatalf("read %s: %v", f.File, err)
	}
	if f.Generate == nil {
		return raw
	}
	base, err := parseNumbers(raw)
	if err != nil {
		t.Fatalf("parse %s: %v", f.File, err)
	}
	body := base.(map[string]any)
	switch f.Generate.Op {
	case "plugins_count":
		job := body["jobs"].([]any)[0].(map[string]any)
		tmpl := job["plugins"].([]any)[0].(map[string]any)
		plugins := make([]any, f.Generate.Count)
		for i := range plugins {
			p := map[string]any{}
			for k, v := range tmpl {
				p[k] = v
			}
			p["plugin_uuid"] = uuidFor(i + 1)
			plugins[i] = p
		}
		job["plugins"] = plugins
	case "packages_count":
		pk := make([]map[string]any, f.Generate.Count)
		items := make([]any, f.Generate.Count)
		for i := range pk {
			name := fmt.Sprintf("pkg-%d", i)
			pk[i] = map[string]any{
				"name": name, "version": "1.0", "architecture": "amd64",
				"status": "install ok installed", "source": name, "installed_size_kb": json.Number("1"),
			}
			items[i] = pk[i]
		}
		body["packages"] = items
		body["list_sha256"] = oracleListSHA256(pk)
	case "ip_addresses_count":
		ips := make([]any, f.Generate.Count)
		for i := range ips {
			ips[i] = fmt.Sprintf("10.%d.%d.%d", i/65536, (i/256)%256, i%256)
		}
		body["os_info"].(map[string]any)["ip_addresses"] = ips
	case "raw_bytes":
		overhead := compactLen(map[string]any{"pad": ""})
		body["os_info"].(map[string]any)["raw"] = map[string]any{"pad": strings.Repeat("a", f.Generate.Bytes-overhead)}
	default:
		t.Fatalf("unknown generate op %q in %s", f.Generate.Op, f.File)
	}
	out, err := json.Marshal(body)
	if err != nil {
		t.Fatalf("marshal %s: %v", f.File, err)
	}
	return out
}

// ---- JSON Schema half (CHK-M4-015; PD-25 (a), test-only validator)

var (
	schemaOnce sync.Once
	schemas    map[string]*jsonschema.Schema
	schemaErr  error
)

const openapiURL = "file:///bitscan/manager/openapi.json"

func componentSchema(t *testing.T, name string) *jsonschema.Schema {
	t.Helper()
	schemaOnce.Do(func() {
		schemas = map[string]*jsonschema.Schema{}
		f, err := os.Open(filepath.Clean(openapiPath))
		if err != nil {
			schemaErr = err
			return
		}
		defer func() { _ = f.Close() }()
		doc, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			schemaErr = err
			return
		}
		c := jsonschema.NewCompiler()
		c.DefaultDraft(jsonschema.Draft2020)
		c.AssertFormat()
		if schemaErr = c.AddResource(openapiURL, doc); schemaErr != nil {
			return
		}
		comps := doc.(map[string]any)["components"].(map[string]any)["schemas"].(map[string]any)
		for n := range comps {
			s, err := c.Compile(openapiURL + "#/components/schemas/" + n)
			if err != nil {
				schemaErr = fmt.Errorf("compile %s: %w", n, err)
				return
			}
			schemas[n] = s
		}
	})
	if schemaErr != nil {
		t.Fatalf("openapi.json schemas: %v", schemaErr)
	}
	s, ok := schemas[name]
	if !ok {
		t.Fatalf("no component %q in manager/openapi.json", name)
	}
	return s
}

func schemaValidate(t *testing.T, component string, body []byte) error {
	t.Helper()
	inst, err := jsonschema.UnmarshalJSON(bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("instance not JSON: %w", err)
	}
	return componentSchema(t, component).Validate(inst)
}

func modelFor(t *testing.T, m manifestDoc, f fixture) string {
	t.Helper()
	r, ok := m.Routes[f.Route]
	if !ok {
		t.Fatalf("route %q not in manifest routes", f.Route)
	}
	ref := r.Request
	if f.Direction == "response" {
		ref = r.Response
	}
	if ref == nil {
		t.Fatalf("%s has no body model", f.key())
	}
	return ref.Model
}

// ---- equivalence of re-encoded bodies

// sameJSON compares parsed values exactly, numbers as exact decimals; it
// allows only the contract's normalisations: a UUID re-encoded in lowercase,
// and a timestamp re-encoded as the same instant.
func sameJSON(a, b any, path string) error {
	switch x := a.(type) {
	case map[string]any:
		y, ok := b.(map[string]any)
		if !ok {
			return fmt.Errorf("%s: object vs %T", path, b)
		}
		if len(x) != len(y) {
			return fmt.Errorf("%s: %d keys vs %d", path, len(x), len(y))
		}
		for k, v := range x {
			w, ok := y[k]
			if !ok {
				return fmt.Errorf("%s: key %q missing after re-encode", path, k)
			}
			if err := sameJSON(v, w, path+"."+k); err != nil {
				return err
			}
		}
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return fmt.Errorf("%s: array length or type differs", path)
		}
		for i := range x {
			if err := sameJSON(x[i], y[i], fmt.Sprintf("%s[%d]", path, i)); err != nil {
				return err
			}
		}
	case json.Number:
		y, ok := b.(json.Number)
		if !ok {
			return fmt.Errorf("%s: number vs %T", path, b)
		}
		rx, okx := new(big.Rat).SetString(string(x))
		ry, oky := new(big.Rat).SetString(string(y))
		if !okx || !oky || rx.Cmp(ry) != 0 {
			return fmt.Errorf("%s: number %s vs %s", path, x, y)
		}
	case string:
		y, ok := b.(string)
		if !ok {
			return fmt.Errorf("%s: string vs %T", path, b)
		}
		if x == y {
			return nil
		}
		if uuidPattern.MatchString(x) && y == strings.ToLower(x) {
			return nil
		}
		if timeTextLike.MatchString(x) {
			tx, ex := time.Parse(time.RFC3339Nano, strings.ToUpper(x))
			ty, ey := time.Parse(time.RFC3339Nano, y)
			if ex == nil && ey == nil && tx.Equal(ty) {
				return nil
			}
		}
		return fmt.Errorf("%s: %q vs %q", path, x, y)
	default:
		if !reflect.DeepEqual(a, b) {
			return fmt.Errorf("%s: %v vs %v", path, a, b)
		}
	}
	return nil
}

// ---- CHK-M4-010: manifest and generate ops

func TestContractManifest(t *testing.T) {
	m := loadManifest(t)
	if len(m.Fixtures) != manifestEntries {
		t.Errorf("manifest has %d entries, want %d", len(m.Fixtures), manifestEntries)
	}
	if !strings.HasPrefix(m.FakeToken, "bsa_FIXTURE_") {
		t.Errorf("fake_token %q is not the fixture token", m.FakeToken)
	}
	if _, ok := m.SchemaGaps["lone surrogate"]; !ok {
		t.Error("schema_gaps has no 'lone surrogate' entry")
	}
	if _, ok := m.SchemaGaps["nan_inf"]; !ok {
		t.Error("schema_gaps has no 'nan_inf' entry")
	}
	seen := map[string]bool{}
	// M10: shared non-wire files (the redaction corpus, TP-M10-03) are
	// listed by name in "shared_files"; each must exist and is counted as
	// listed, never as a wire fixture.
	wantShared := []string{"redaction/corpus.json"}
	if len(m.SharedFiles) != len(wantShared) {
		t.Errorf("shared_files has %d entries, want %v", len(m.SharedFiles), wantShared)
	}
	for i, s := range m.SharedFiles {
		if i < len(wantShared) && s.File != wantShared[i] {
			t.Errorf("shared_files[%d] = %s, want %s", i, s.File, wantShared[i])
		}
		if seen[s.File] {
			t.Errorf("duplicate shared_files entry %s", s.File)
		}
		seen[s.File] = true
		if _, err := os.Stat(filepath.Join(fixturesDir, filepath.FromSlash(s.File))); err != nil {
			t.Errorf("shared_files entry %s: %v", s.File, err)
		}
	}
	shared := maps.Clone(seen)
	classes := map[string]map[string]bool{}
	for _, f := range m.Fixtures {
		if shared[f.File] {
			t.Errorf("%s is both a wire fixture and a shared file", f.File)
		}
		if seen[f.File] {
			t.Errorf("duplicate manifest entry %s", f.File)
		}
		seen[f.File] = true
		if _, err := os.Stat(filepath.Join(fixturesDir, filepath.FromSlash(f.File))); err != nil {
			t.Errorf("manifest entry %s: %v", f.File, err)
		}
		if _, ok := decoders[f.key()]; !ok {
			t.Errorf("%s: no Go type for body %s", f.File, f.key())
		}
		if f.SchemaGap != "" {
			if _, ok := m.SchemaGaps[f.SchemaGap]; !ok {
				t.Errorf("%s: schema_gap %q not described in schema_gaps", f.File, f.SchemaGap)
			}
			if f.Valid {
				t.Errorf("%s: a schema_gap entry must be invalid", f.File)
			}
		}
		if !f.Valid {
			if classes[f.key()] == nil {
				classes[f.key()] = map[string]bool{}
			}
			classes[f.key()][f.Class] = true
		}
	}
	for key, want := range m.RequiredInvalidClasses {
		for _, c := range want {
			if !classes[key][c] {
				t.Errorf("%s: no invalid fixture of class %s", key, c)
			}
		}
	}
	// every file on disk is in the manifest
	err := filepath.WalkDir(fixturesDir, func(p string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() || d.Name() == "manifest.json" {
			return err
		}
		rel, _ := filepath.Rel(fixturesDir, p)
		if !seen[filepath.ToSlash(rel)] {
			t.Errorf("fixture %s is not in the manifest", filepath.ToSlash(rel))
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

// The generated bodies equal what manager/tests/contract/loader.py builds
// (values computed with loader.py on 2026-10-24).
func TestContractGenerateMatchesPythonLoader(t *testing.T) {
	m := loadManifest(t)
	wantHash := map[string]string{
		"inventory/request_valid_packages_50000":   "36004435592aafd2e16b33b19de61670e123d297f77aa36be9091da11f1c80ba",
		"inventory/request_invalid_packages_50001": "3ff19eb624b1c790790a1dc2b7f33ff26fc433c4415a1840fb34b399456db3a0",
	}
	generated := 0
	for _, f := range m.Fixtures {
		if f.Generate == nil {
			continue
		}
		generated++
		v, err := parseNumbers(fixtureBody(t, f))
		if err != nil {
			t.Fatalf("%s: %v", f.File, err)
		}
		body := v.(map[string]any)
		switch f.Generate.Op {
		case "plugins_count":
			plugins := body["jobs"].([]any)[0].(map[string]any)["plugins"].([]any)
			if len(plugins) != f.Generate.Count {
				t.Errorf("%s: %d plugins, want %d", f.File, len(plugins), f.Generate.Count)
			}
			first := plugins[0].(map[string]any)["plugin_uuid"]
			last := plugins[len(plugins)-1].(map[string]any)["plugin_uuid"]
			if first != "00000000-0000-4000-8000-000000000001" || last != uuidFor(f.Generate.Count) {
				t.Errorf("%s: plugin uuids %v .. %v", f.File, first, last)
			}
		case "packages_count":
			if n := len(body["packages"].([]any)); n != f.Generate.Count {
				t.Errorf("%s: %d packages", f.File, n)
			}
			if got := body["list_sha256"]; got != wantHash[f.name()] {
				t.Errorf("%s: list_sha256 %v, loader.py gives %s", f.File, got, wantHash[f.name()])
			}
		case "ip_addresses_count":
			ips := body["os_info"].(map[string]any)["ip_addresses"].([]any)
			if len(ips) != f.Generate.Count {
				t.Errorf("%s: %d addresses", f.File, len(ips))
			}
		case "raw_bytes":
			if n := compactLen(body["os_info"].(map[string]any)["raw"]); n != f.Generate.Bytes {
				t.Errorf("%s: raw is %d bytes compact, want %d", f.File, n, f.Generate.Bytes)
			}
		}
	}
	if generated != 8 {
		t.Errorf("%d generated fixtures, want 8", generated)
	}
	if got := oracleListSHA256(nil); got != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" {
		t.Errorf("empty list hash %s", got)
	}
}

// ---- CHK-M4-011 to -015: every fixture through the Go types and the schemas

func TestContractFixtures(t *testing.T) {
	m := loadManifest(t)
	for _, f := range m.Fixtures {
		t.Run(f.name(), func(t *testing.T) {
			if f.SchemaGap == "lone surrogate" {
				t.Skip("schema_gap lone surrogate: Go decodes \\ud800 as U+FFFD; the Go test asserts nothing (decisions 2026-10-23, 2026-10-24)")
			}
			body := fixtureBody(t, f)
			decode := decoders[f.key()]
			component := modelFor(t, m, f)
			got, err := decode(body)

			if f.SchemaGap == "nan_inf" {
				// Ruling 2026-10-24: must be refused. NaN and Infinity are not
				// JSON; 1e400 is JSON number syntax that overflows float64.
				if err == nil {
					t.Fatalf("nan_inf fixture accepted by DecodeStrict")
				}
				if !strings.Contains(f.File, "1e400") && json.Valid(body) {
					t.Errorf("expected a JSON parse error, but the body is valid JSON")
				}
				return
			}

			if !f.Valid {
				if err == nil {
					t.Fatalf("invalid fixture (%s: %s) accepted: %+v", f.Class, f.Reason, got)
				}
				// The schema must refuse it too (the manifest's validity is
				// the schema's; only schema_gap entries differ).
				if serr := schemaValidate(t, component, body); serr == nil {
					t.Errorf("the %s schema accepts this invalid fixture (manifest says invalid)", component)
				}
				return
			}

			if err != nil {
				t.Fatalf("valid fixture refused: %v", err)
			}
			if serr := schemaValidate(t, component, body); serr != nil {
				t.Fatalf("fixture does not validate against %s: %v", component, serr)
			}
			if f.Direction == "response" {
				// REQ-091 (1): responses must decode; only requests (what the
				// agent sends) must re-encode to equivalent JSON.
				return
			}
			enc, err := wire.Encode(got)
			if err != nil {
				t.Fatalf("Encode of a decoded valid fixture failed: %v", err)
			}
			want, _ := parseNumbers(body)
			have, err := parseNumbers(enc)
			if err != nil {
				t.Fatalf("re-encoded body is not JSON: %v", err)
			}
			if err := sameJSON(want, have, "body"); err != nil {
				t.Errorf("re-encoded body differs from the fixture: %v", err)
			}
			if serr := schemaValidate(t, component, enc); serr != nil {
				t.Errorf("re-encoded body does not validate against %s: %v", component, serr)
			}
		})
	}
}

// ---- CHK-M4-016: REQ-091 (3) and format edge cases

func mutate(t *testing.T, file string, edit func(map[string]any)) []byte {
	t.Helper()
	raw, err := os.ReadFile(filepath.Clean(filepath.Join(fixturesDir, filepath.FromSlash(file))))
	if err != nil {
		t.Fatal(err)
	}
	v, err := parseNumbers(raw)
	if err != nil {
		t.Fatal(err)
	}
	edit(v.(map[string]any))
	out, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

func firstJob(m map[string]any) map[string]any { return m["jobs"].([]any)[0].(map[string]any) }

func TestContractREQ091Cases(t *testing.T) {
	const inv = "jobs/response_valid_inventory.json"
	t.Run("extra key refused", func(t *testing.T) {
		b := mutate(t, inv, func(m map[string]any) { firstJob(m)["command"] = "id" })
		var v wire.JobsResponse
		if err := wire.DecodeStrict(b, &v); err == nil {
			t.Fatal("extra key accepted")
		}
	})
	t.Run("missing nullable key refused", func(t *testing.T) {
		b := mutate(t, "heartbeat/request_valid_full.json", func(m map[string]any) { delete(m, "current_job_id") })
		var v wire.HeartbeatRequest
		if err := wire.DecodeStrict(b, &v); err == nil {
			t.Fatal("missing nullable key accepted")
		}
	})
	t.Run("pickup_by with microseconds accepted", func(t *testing.T) {
		b := mutate(t, inv, func(m map[string]any) { firstJob(m)["pickup_by"] = "2026-10-20T12:00:00.000000Z" })
		var v wire.JobsResponse
		if err := wire.DecodeStrict(b, &v); err != nil {
			t.Fatalf("refused: %v", err)
		}
		want := time.Date(2026, 10, 20, 12, 0, 0, 0, time.UTC)
		if got := v.Jobs[0].PickupBy.Time(); !got.Equal(want) {
			t.Fatalf("pickup_by %v, want %v", got, want)
		}
	})
	t.Run("uppercase UUID accepted and sent lowercase", func(t *testing.T) {
		up := "6F1C2B3A-4D5E-4F60-8A7B-9C0D1E2F3A4B"
		b := mutate(t, inv, func(m map[string]any) { firstJob(m)["agent_id"] = up })
		var v wire.JobsResponse
		if err := wire.DecodeStrict(b, &v); err != nil {
			t.Fatalf("refused: %v", err)
		}
		if v.Jobs[0].AgentID != wire.UUID(strings.ToLower(up)) {
			t.Fatalf("agent_id %q, want the lowercase id", v.Jobs[0].AgentID)
		}
		enc, err := wire.Encode(&v)
		if err != nil || !bytes.Contains(enc, []byte(strings.ToLower(up))) || bytes.Contains(enc, []byte(up)) {
			t.Fatalf("encoded %s (%v), want the lowercase id", enc, err)
		}
	})
	accept := map[string]string{
		"offset +08:00":        "2026-10-20T20:00:00+08:00",
		"offset -05:30":        "2026-10-20T06:30:00-05:30",
		"lowercase t and z":    "2026-10-20t12:00:00z",
		"nine fraction digits": "2026-10-20T12:00:00.123456789Z",
		"leap day":             "2028-02-29T00:00:00Z",
	}
	for name, ts := range accept {
		t.Run("pickup_by accepted: "+name, func(t *testing.T) {
			b := mutate(t, inv, func(m map[string]any) { firstJob(m)["pickup_by"] = ts })
			var v wire.JobsResponse
			if err := wire.DecodeStrict(b, &v); err != nil {
				t.Fatalf("%s refused: %v", ts, err)
			}
		})
	}
	refuse := map[string]any{
		"naive":               "2026-10-20T12:00:00",
		"date only":           "2026-10-20",
		"space separator":     "2026-10-20 12:00:00Z",
		"ten fraction digits": "2026-10-20T12:00:00.1234567890Z",
		"30 February":         "2026-02-30T12:00:00Z",
		"29 February 2026":    "2026-02-29T12:00:00Z",
		"leap second":         "2026-12-31T23:59:60Z",
		"hour 24":             "2026-10-20T24:00:00Z",
		"offset +24:00":       "2026-10-20T12:00:00+24:00",
		"epoch number":        json.Number("1792800000"),
		"empty":               "",
		"null":                nil,
	}
	for name, ts := range refuse {
		t.Run("pickup_by refused: "+name, func(t *testing.T) {
			b := mutate(t, inv, func(m map[string]any) { firstJob(m)["pickup_by"] = ts })
			var v wire.JobsResponse
			if err := wire.DecodeStrict(b, &v); err == nil {
				t.Fatalf("%v accepted", ts)
			}
		})
	}
	badUUID := map[string]string{
		"32 hex":      "6f1c2b3a4d5e4f608a7b9c0d1e2f3a4b",
		"braces":      "{6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b}",
		"urn":         "urn:uuid:6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b",
		"short group": "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4",
		"non hex":     "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4g",
		"trailing nl": "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b\n",
		"empty":       "",
	}
	for name, id := range badUUID {
		t.Run("agent_id refused: "+name, func(t *testing.T) {
			b := mutate(t, inv, func(m map[string]any) { firstJob(m)["agent_id"] = id })
			var v wire.JobsResponse
			if err := wire.DecodeStrict(b, &v); err == nil {
				t.Fatalf("%q accepted", id)
			}
		})
	}
	whole := map[string]string{
		"trailing data":         `{"job_pull_seconds":300,"max_parallel_plugins":2,"server_time":"2026-10-19T08:00:00Z"} {}`,
		"case-variant key":      `{"job_pull_seconds":300,"max_parallel_plugins":2,"server_time":"2026-10-19T08:00:00Z","JOB_PULL_SECONDS":9999}`,
		"case-variant key only": `{"Job_Pull_Seconds":300,"max_parallel_plugins":2,"server_time":"2026-10-19T08:00:00Z"}`,
		"byte order mark":       "\xef\xbb\xbf" + `{"job_pull_seconds":300,"max_parallel_plugins":2,"server_time":"2026-10-19T08:00:00Z"}`,
		"top-level array":       `[{"job_pull_seconds":300,"max_parallel_plugins":2,"server_time":"2026-10-19T08:00:00Z"}]`,
		"top-level null":        `null`,
		"empty body":            ``,
		"truncated":             `{"job_pull_seconds":300,"max_parallel_plugins":2,"server_time":"2026-10-19T08:00:00Z"`,
	}
	for name, body := range whole {
		t.Run("heartbeat response refused: "+name, func(t *testing.T) {
			var v wire.HeartbeatResponse
			if err := wire.DecodeStrict([]byte(body), &v); err == nil {
				t.Fatalf("accepted: %+v", v)
			}
		})
	}
}

// ---- CHK-M4-017: no omitempty; Go json names equal the schema properties

func TestContractNoOmitemptyAndExactKeys(t *testing.T) {
	type pair struct {
		goType     reflect.Type
		components []string // the Go struct's keys = the union of these
	}
	pairs := []pair{
		{reflect.TypeFor[wire.EnrolRequest](), []string{"EnrolRequest"}},
		{reflect.TypeFor[wire.EnrolResponse](), []string{"EnrolResponse"}},
		{reflect.TypeFor[wire.HeartbeatRequest](), []string{"HeartbeatRequest"}},
		{reflect.TypeFor[wire.HeartbeatResponse](), []string{"HeartbeatResponse"}},
		{reflect.TypeFor[wire.JobsResponse](), []string{"JobsResponse"}},
		{reflect.TypeFor[wire.Job](), []string{"InventoryJob", "ComplianceJob"}},
		{reflect.TypeFor[wire.PluginSpec](), []string{"PluginSpec"}},
		{reflect.TypeFor[wire.ResultsRequest](), []string{"ResultsRequest"}},
		{reflect.TypeFor[wire.ResultItem](), []string{"ResultItem"}},
		{reflect.TypeFor[wire.ResultsResponse](), []string{"ResultsResponse"}},
		{reflect.TypeFor[wire.InventoryBody](), []string{"InventoryBody"}},
		{reflect.TypeFor[wire.OsInfo](), []string{"OsInfo"}},
		{reflect.TypeFor[wire.PackageItem](), []string{"PackageItem"}},
		{reflect.TypeFor[wire.RotateRequest](), []string{"RotateRequest"}},
		{reflect.TypeFor[wire.RotateResponse](), []string{"RotateResponse"}},
	}
	raw, err := os.ReadFile(filepath.Clean(openapiPath))
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		Components struct {
			Schemas map[string]struct {
				Properties map[string]json.RawMessage `json:"properties"`
				Required   []string                   `json:"required"`
			} `json:"schemas"`
		} `json:"components"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	for _, p := range pairs {
		want := map[string]bool{}
		for _, c := range p.components {
			s, ok := doc.Components.Schemas[c]
			if !ok {
				t.Fatalf("component %s missing", c)
			}
			for k := range s.Properties {
				want[k] = true
			}
			// every property is required in the agent contract (#60: nullable keys are required)
			if len(s.Required) != len(s.Properties) {
				t.Errorf("%s: %d required of %d properties", c, len(s.Required), len(s.Properties))
			}
		}
		got := map[string]bool{}
		for i := range p.goType.NumField() {
			f := p.goType.Field(i)
			if !f.IsExported() {
				continue
			}
			tag, ok := f.Tag.Lookup("json")
			if !ok {
				t.Errorf("%s.%s has no json tag", p.goType.Name(), f.Name)
				continue
			}
			name, opts, _ := strings.Cut(tag, ",")
			if opts != "" {
				t.Errorf("%s.%s json tag %q has options (omitempty, omitzero and string are not allowed)", p.goType.Name(), f.Name, tag)
			}
			if name == "" || name == "-" {
				t.Errorf("%s.%s json name %q", p.goType.Name(), f.Name, name)
				continue
			}
			got[name] = true
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s keys %v, schema %v has %v", p.goType.Name(), sortedKeys(got), p.components, sortedKeys(want))
		}
	}
	// source grep over the non-test files of the package
	files, _ := filepath.Glob("*.go")
	for _, fn := range files {
		if strings.HasSuffix(fn, "_test.go") {
			continue
		}
		src, err := os.ReadFile(filepath.Clean(fn))
		if err != nil {
			t.Fatal(err)
		}
		for _, bad := range []string{"omitempty", "omitzero"} {
			if bytes.Contains(src, []byte(bad)) {
				t.Errorf("%s contains %q", fn, bad)
			}
		}
	}
}

func sortedKeys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// ---- CHK-M4-018: strict integers and bounds, cross-checked with the schema

func TestContractIntegerBounds(t *testing.T) {
	type field struct {
		file, component string
		set             func(map[string]any, any)
		accept, refuse  []any
	}
	hb := "heartbeat/response_valid_defaults.json"
	pl := "jobs/response_valid_compliance.json"
	rr := "results/response_valid_counts.json"
	n := func(s string) any { return json.Number(s) }
	fields := map[string]field{
		"job_pull_seconds": {hb, "HeartbeatResponse", func(m map[string]any, v any) { m["job_pull_seconds"] = v },
			[]any{n("60"), n("300"), n("3600")},
			[]any{n("59"), n("3601"), n("0"), n("-1"), n("300.0"), n("3e2"), n("9007199254740992"), "300", true, nil}},
		"max_parallel_plugins": {hb, "HeartbeatResponse", func(m map[string]any, v any) { m["max_parallel_plugins"] = v },
			[]any{n("1"), n("8")},
			[]any{n("0"), n("9"), n("2.5"), n("1.0"), "2", false, nil}},
		"timeout_s": {pl, "JobsResponse", func(m map[string]any, v any) {
			firstJob(m)["plugins"].([]any)[0].(map[string]any)["timeout_s"] = v
		},
			[]any{n("1"), n("600")},
			[]any{n("0"), n("601"), n("30.0"), n("1e1"), "30", true}},
		"accepted": {rr, "ResultsResponse", func(m map[string]any, v any) { m["accepted"] = v },
			[]any{n("0"), n("50"), n("9007199254740991")},
			[]any{n("-1"), n("1.5"), n("1.0"), "1", true, nil}},
		"duplicates": {rr, "ResultsResponse", func(m map[string]any, v any) { m["duplicates"] = v },
			[]any{n("0"), n("3")},
			[]any{n("-1"), n("0.5"), "0", false, nil}},
	}
	for name, f := range fields {
		for _, v := range f.accept {
			t.Run(fmt.Sprintf("%s=%v accepted", name, v), func(t *testing.T) {
				b := mutate(t, f.file, func(m map[string]any) { f.set(m, v) })
				if _, err := decoders[map[string]string{
					"HeartbeatResponse": "heartbeat/response", "JobsResponse": "jobs/response", "ResultsResponse": "results/response",
				}[f.component]](b); err != nil {
					t.Fatalf("refused: %v", err)
				}
				if err := schemaValidate(t, f.component, b); err != nil {
					t.Fatalf("schema refuses a value the test expects valid: %v", err)
				}
			})
		}
		for _, v := range f.refuse {
			t.Run(fmt.Sprintf("%s=%v refused", name, v), func(t *testing.T) {
				b := mutate(t, f.file, func(m map[string]any) { f.set(m, v) })
				if _, err := decoders[map[string]string{
					"HeartbeatResponse": "heartbeat/response", "JobsResponse": "jobs/response", "ResultsResponse": "results/response",
				}[f.component]](b); err == nil {
					t.Fatalf("accepted %s", b)
				}
			})
		}
	}
}

// ---- CHK-M4-019: problem bodies

func TestContractProblemBodies(t *testing.T) {
	types := []string{
		"pending_approval", "enrollment_rejected", "token_revoked", "token_expired",
		"machine_id_mismatch", "job_not_acceptable", "too_large", "rate_limited",
		"unauthorized", "forbidden", "invalid_request", "about:blank",
	}
	for i, typ := range types {
		status := 400 + i
		body := fmt.Sprintf(`{"type":%q,"title":"t","status":%d,"detail":"d","instance":"/api/v1/agent/x","extra":{"a":[1]}}`, typ, status)
		p, err := wire.DecodeProblem([]byte(body))
		if err != nil {
			t.Fatalf("%s: %v", typ, err)
		}
		if p.Type != typ || p.Status != status {
			t.Errorf("%s: decoded %+v", typ, p)
		}
	}
	if p, err := wire.DecodeProblem([]byte(`{"status":403}`)); err != nil || p.Type != "about:blank" || p.Status != 403 {
		t.Errorf("missing type: %+v, %v", p, err)
	}
	for _, bad := range []string{"", "<html>502</html>", "null", "[]", `{"type":`} {
		func() {
			defer func() {
				if r := recover(); r != nil {
					t.Errorf("DecodeProblem(%q) panicked: %v", bad, r)
				}
			}()
			p, err := wire.DecodeProblem([]byte(bad))
			if err == nil && p.Type != "about:blank" && p.Type != "" {
				t.Errorf("DecodeProblem(%q) = %+v", bad, p)
			}
		}()
	}
}

// ---- REQ-091 (2) for bodies the agent builds itself, and secrets in output

func TestContractAgentBuiltRequests(t *testing.T) {
	loc := time.FixedZone("UTC+8", 8*3600)
	clock := wire.NewTime(time.Date(2026, 10, 24, 20, 0, 0, 123000000, loc))
	job := wire.UUID("C1A4E5F6-0718-4293-A4B5-C6D7E8F9A0B1")
	hb := wire.HeartbeatRequest{
		AgentVersion: "0.1.0~pre1", UptimeS: 0, LastPullAt: nil, CurrentJobID: &job,
		SpoolBytes: 0, LastError: nil, RunnerHelpers: []wire.HelperName{}, Clock: clock,
	}
	enc, err := wire.Encode(&hb)
	if err != nil {
		t.Fatalf("Encode: %v", err)
	}
	if err := schemaValidate(t, "HeartbeatRequest", enc); err != nil {
		t.Fatalf("agent-built heartbeat does not validate: %v (%s)", err, enc)
	}
	var m map[string]any
	if err := json.Unmarshal(enc, &m); err != nil {
		t.Fatal(err)
	}
	if m["clock"] != "2026-10-24T12:00:00.123Z" {
		t.Errorf("clock %v, want UTC with Z", m["clock"])
	}
	if m["current_job_id"] != strings.ToLower(string(job)) {
		t.Errorf("current_job_id %v, want lowercase", m["current_job_id"])
	}
	for _, k := range []string{"last_pull_at", "last_error"} {
		if v, ok := m[k]; !ok || v != nil {
			t.Errorf("%s: present=%v value=%v, want present and null", k, ok, v)
		}
	}
	if string(mustJSON(t, m["runner_helpers"])) != "[]" {
		t.Errorf("runner_helpers %v, want []", m["runner_helpers"])
	}

	// self-check refusals before sending
	bad := hb
	bad.RunnerHelpers = nil
	if _, err := wire.Encode(&bad); err == nil {
		t.Error("nil runner_helpers (would encode as null) accepted")
	}
	bad = hb
	bad.RunnerHelpers = []wire.HelperName{"capread", "capread"}
	if _, err := wire.Encode(&bad); err == nil {
		t.Error("duplicate runner_helpers accepted")
	}
	bad = hb
	e := strings.Repeat("x", 1025)
	bad.LastError = &e
	if _, err := wire.Encode(&bad); err == nil {
		t.Error("last_error of 1,025 characters accepted")
	}
	bad = hb
	bad.UptimeS = 9007199254740992
	if _, err := wire.Encode(&bad); err == nil {
		t.Error("uptime_s 2^53 accepted")
	}
	enrol := wire.EnrolRequest{Hostname: "host\x00", MachineID: "0123456789abcdef0123456789abcdef", AgentVersion: "0.1.0"}
	if _, err := wire.Encode(&enrol); err == nil {
		t.Error("U+0000 in hostname accepted")
	}
	enrol.Hostname = "h<b>&"
	out, err := wire.Encode(&enrol)
	if err != nil {
		t.Fatalf("enrol: %v", err)
	}
	if !bytes.Contains(out, []byte(`"h<b>&"`)) {
		t.Errorf("HTML characters escaped: %s", out)
	}
	if !bytes.Contains(out, []byte(`"os_id":null`)) {
		t.Errorf("nullable os_id not sent as null: %s", out)
	}
	if err := schemaValidate(t, "EnrolRequest", out); err != nil {
		t.Errorf("enrol body does not validate: %v", err)
	}
	res := wire.ResultsRequest{Results: []wire.ResultItem{}, Final: false}
	if out, err := wire.Encode(&res); err != nil || string(out) != `{"results":[],"final":false}` {
		t.Errorf("start notice %s, %v", out, err)
	}
	if out, err := wire.Encode(&wire.RotateRequest{}); err != nil || string(out) != `{}` {
		t.Errorf("rotate body %s, %v", out, err)
	}
}

func mustJSON(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// The agent token never appears in formatted output (security invariants:
// no token in logs). JSON encoding must still carry it.
func TestContractTokenNeverPrinted(t *testing.T) {
	const tok = "bsa_CANARY0123456789abcdef_CANARY0123456789abcd"
	if len(tok) != 47 {
		t.Fatalf("canary token length %d", len(tok))
	}
	body := fmt.Sprintf(`{"agent_token":%q,"issued_at":"2026-10-24T00:00:00Z","expires_at":"2027-10-24T00:00:00Z"}`, tok)
	var r wire.RotateResponse
	if err := wire.DecodeStrict([]byte(body), &r); err != nil {
		t.Fatalf("decode: %v", err)
	}
	for _, verb := range []string{"%v", "%+v", "%#v", "%s", "%q"} {
		for _, v := range []any{r, &r, r.AgentToken} {
			if s := fmt.Sprintf(verb, v); strings.Contains(s, "CANARY") {
				t.Errorf("fmt %s of %T prints the token: %s", verb, v, s)
			}
		}
	}
	if string(r.AgentToken) != tok {
		t.Error("token value lost")
	}
	enc, err := wire.Encode(&r)
	if err != nil || !bytes.Contains(enc, []byte(tok)) {
		t.Errorf("encoded rotate response lost the token: %v", err)
	}
	// a refused body never echoes the token in the error
	bad := strings.Replace(body, `"issued_at"`, `"issued"`, 1)
	if err := wire.DecodeStrict([]byte(bad), &r); err == nil || strings.Contains(err.Error(), "CANARY") {
		t.Errorf("error %v", err)
	}
}
