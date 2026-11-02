// TP-M10-02 (tester-m10): the agent–runner protocol, REQ-234 and #130.
// Expected values come from REQ-234, #130 (b)–(d), #131 (b), #140 and the
// lead's Q1 answer (out-of-bound jobs are `malformed` on the socket), never
// from the implementation. Pure Go: runs on Windows and Linux.
package proto_test

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"io/fs"
	"maps"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"sort"
	"strings"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

const (
	agentID  = "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"
	jobID    = "d2b5f607-1829-43a4-b5c6-d7e8f9a0b1c2"
	pluginID = "3f6c2a9e-8b1d-4e57-9a3c-2d7f0e6b1c48"
	canary   = "M10CANARY-7f3a9c"
)

var allWords = []string{
	"busy", "malformed", "not_compliance", "bad_plugins", "bad_parallel",
	"bad_patterns", "agent_id_unreadable", "foreign_agent", "pickup_passed",
	"pickup_too_far", "replayed", "seen_full", "internal",
}

// frame builds a raw frame: 4-byte big-endian length then the body.
func frame(body []byte) []byte {
	n := len(body)
	if n < 0 || n > math.MaxUint32 {
		panic("frame too big")
	}
	b := binary.BigEndian.AppendUint32(make([]byte, 0, 4+n), uint32(n))
	return append(b, body...)
}

func header(n uint32) []byte {
	b := make([]byte, 4)
	binary.BigEndian.PutUint32(b, n)
	return b
}

// jobJSON is a valid compliance job as raw JSON.
func jobJSON(plugins string, patterns string) string {
	if plugins == "" {
		plugins = `[{"plugin_uuid":"` + pluginID + `","execute":"dpkg-query -W -f='${Status}' apparmor 2>/dev/null","timeout_s":30}]`
	}
	if patterns == "" {
		patterns = `["<RE2 pattern>"]`
	}
	return `{"job_id":"` + jobID + `","agent_id":"` + agentID + `","kind":"compliance","pickup_by":"2026-10-19T08:00:00Z","plugins":` + plugins + `,"redaction_patterns":` + patterns + `}`
}

func reqJSON(job string, mpp string) string {
	return `{"v":1,"job":` + job + `,"max_parallel_plugins":` + mpp + `}`
}

func validJob(t *testing.T) wire.Job {
	t.Helper()
	var j wire.Job
	if err := wire.DecodeStrict([]byte(jobJSON("", "")), &j); err != nil {
		t.Fatalf("test job does not decode: %v", err)
	}
	return j
}

func ptr[T any](v T) *T { return &v }

func validItem() wire.ResultItem {
	return wire.ResultItem{
		PluginUUID: pluginID,
		ExitCode:   ptr(int64(0)),
		Stdout:     "install ok installed",
		Stderr:     "",
		StartedAt:  wire.NewTime(time.Date(2026, 10, 30, 8, 0, 0, 0, time.UTC)),
		FinishedAt: wire.NewTime(time.Date(2026, 10, 30, 8, 0, 1, 0, time.UTC)),
	}
}

func itemJSON(t *testing.T, it wire.ResultItem) map[string]any {
	t.Helper()
	b, err := json.Marshal(it)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	return m
}

// failAfter is a reader that serves data and fails the test on any read once
// limit bytes were served (it proves an oversize body is never read).
type failAfter struct {
	t     *testing.T
	data  []byte
	limit int
	n     int
}

func (f *failAfter) Read(p []byte) (int, error) {
	if f.n >= f.limit {
		f.t.Errorf("read past %d bytes", f.limit)
		return 0, errors.New("read past limit")
	}
	end := min(f.limit, len(f.data), f.n+len(p))
	c := copy(p, f.data[f.n:end])
	f.n += c
	return c, nil
}

// CHK-M10-001: every frame type round-trips; frames are a 4-byte BE length
// then one compact JSON object.
func TestRoundTrip(t *testing.T) {
	t.Run("request", func(t *testing.T) {
		req := proto.Request{V: 1, Job: validJob(t), MaxParallelPlugins: 3}
		var buf bytes.Buffer
		if err := proto.WriteRequest(&buf, req); err != nil {
			t.Fatalf("WriteRequest: %v", err)
		}
		raw := buf.Bytes()
		n := binary.BigEndian.Uint32(raw[:4])
		if int(n) != len(raw)-4 {
			t.Fatalf("header %d, body %d", n, len(raw)-4)
		}
		var compact bytes.Buffer
		if err := json.Compact(&compact, raw[4:]); err != nil || !bytes.Equal(compact.Bytes(), raw[4:]) {
			t.Fatalf("body is not compact JSON: %q", raw[4:])
		}
		got, err := proto.ReadRequest(bytes.NewReader(raw))
		if err != nil {
			t.Fatalf("ReadRequest: %v", err)
		}
		if !reflect.DeepEqual(got, req) {
			t.Fatalf("round trip differs:\n got %+v\nwant %+v", got, req)
		}
	})
	replies := []proto.Reply{{Kind: proto.KindAccepted}, {Kind: proto.KindDone}}
	for _, w := range allWords {
		replies = append(replies, proto.Reply{Kind: proto.KindRefused, Reason: proto.Reason(w)})
	}
	items := []wire.ResultItem{validItem()}
	it := validItem()
	it.ExitCode = nil
	it.Error = ptr(wire.ErrRunnerUnavailable)
	it.Stdout = ""
	items = append(items, it)
	it = validItem()
	it.Stdout = "é€😀 " + strings.Repeat("\x00", 3) + "\"\\<>&"
	it.Stderr = "warn\n"
	it.ExitCode = ptr(int64(137))
	it.TimedOut, it.Truncated = true, true
	items = append(items, it)
	for _, item := range items {
		r, err := proto.NewResult(item)
		if err != nil {
			t.Fatalf("NewResult(%+v): %v", item, err)
		}
		replies = append(replies, proto.Reply{Kind: proto.KindResult, Result: r})
	}
	for _, rep := range replies {
		t.Run(string(rep.Kind)+"/"+string(rep.Reason), func(t *testing.T) {
			var buf bytes.Buffer
			if err := proto.WriteReply(&buf, rep); err != nil {
				t.Fatalf("WriteReply: %v", err)
			}
			raw := buf.Bytes()
			if int(binary.BigEndian.Uint32(raw[:4])) != len(raw)-4 {
				t.Fatal("bad header")
			}
			var m map[string]any
			if err := json.Unmarshal(raw[4:], &m); err != nil || m["type"] != string(rep.Kind) {
				t.Fatalf("wire shape %q", raw[4:])
			}
			var compact bytes.Buffer
			if err := json.Compact(&compact, raw[4:]); err != nil || !bytes.Equal(compact.Bytes(), raw[4:]) {
				t.Fatalf("not compact: %q", raw[4:])
			}
			got, err := proto.ReadReply(bytes.NewReader(raw))
			if err != nil {
				t.Fatalf("ReadReply: %v", err)
			}
			if got.Kind != rep.Kind || got.Reason != rep.Reason {
				t.Fatalf("got %+v want %+v", got, rep)
			}
			if rep.Kind == proto.KindResult && !reflect.DeepEqual(itemJSON(t, got.Result.Item()), itemJSON(t, rep.Result.Item())) {
				t.Fatalf("result differs: %+v vs %+v", got.Result.Item(), rep.Result.Item())
			}
		})
	}
	// Exact wire shapes of the four replies (#130 (d)).
	shapes := map[string]proto.Reply{
		`{"type":"accepted"}`:                    {Kind: proto.KindAccepted},
		`{"type":"done"}`:                        {Kind: proto.KindDone},
		`{"type":"refused","reason":"busy"}`:     {Kind: proto.KindRefused, Reason: proto.ReasonBusy},
		`{"type":"refused","reason":"replayed"}`: {Kind: proto.KindRefused, Reason: proto.ReasonReplayed},
	}
	for want, rep := range shapes {
		var buf bytes.Buffer
		if err := proto.WriteReply(&buf, rep); err != nil {
			t.Fatal(err)
		}
		if got := string(buf.Bytes()[4:]); got != want {
			t.Errorf("wire %s, want %s", got, want)
		}
	}
}

// CHK-M10-002: each compliance job from the contract fixtures is carried
// unchanged.
func TestContractFixtureJobsCarriedUnchanged(t *testing.T) {
	dir := filepath.Join("..", "..", "..", "..", "manager", "tests", "contract", "fixtures", "jobs")
	files, err := filepath.Glob(filepath.Join(dir, "response_valid_*.json"))
	if err != nil || len(files) == 0 {
		t.Fatalf("no fixtures in %s: %v", dir, err)
	}
	seen := 0
	for _, f := range files {
		raw, err := fs.ReadFile(os.DirFS(dir), filepath.Base(f))
		if err != nil {
			t.Fatal(err)
		}
		var doc struct {
			Jobs []json.RawMessage `json:"jobs"`
		}
		if err := json.Unmarshal(raw, &doc); err != nil {
			t.Fatal(err)
		}
		for i, jraw := range doc.Jobs {
			var job wire.Job
			if err := wire.DecodeStrict(jraw, &job); err != nil {
				t.Fatalf("%s job %d: %v", f, i, err)
			}
			if job.Kind != wire.KindCompliance {
				continue
			}
			seen++
			var buf bytes.Buffer
			if err := proto.WriteRequest(&buf, proto.Request{V: 1, Job: job, MaxParallelPlugins: 2}); err != nil {
				t.Fatalf("%s job %d: WriteRequest: %v", f, i, err)
			}
			got, err := proto.ReadRequest(&buf)
			if err != nil {
				t.Fatalf("%s job %d: ReadRequest: %v", f, i, err)
			}
			gotJSON, _ := json.Marshal(got.Job)
			var a, b any
			_ = json.Unmarshal(gotJSON, &a)
			_ = json.Unmarshal(jraw, &b)
			if !reflect.DeepEqual(a, b) {
				t.Fatalf("%s job %d changed in transit", f, i)
			}
		}
	}
	if seen < 3 {
		t.Fatalf("only %d compliance fixture jobs", seen)
	}
}

// CHK-M10-003: request refusals at decode, and the word RefusalFor gives
// (Q1: `malformed` for everything except an inventory job).
func TestRequestRefusals(t *testing.T) {
	good := jobJSON("", "")
	inv := `{"job_id":"` + jobID + `","agent_id":"` + agentID + `","kind":"inventory","pickup_by":"2026-10-19T08:00:00Z"}`
	plugin := func(timeout string) string {
		return `[{"plugin_uuid":"` + pluginID + `","execute":"echo","timeout_s":` + timeout + `}]`
	}
	many := func(n int) string {
		var parts []string
		for i := range n {
			parts = append(parts, `{"plugin_uuid":"00000000-0000-4000-8000-`+leftPad(i)+`","execute":"echo","timeout_s":5}`)
		}
		return "[" + strings.Join(parts, ",") + "]"
	}
	cases := []struct {
		name string
		body string
		word proto.Reason
	}{
		{"command beside job", `{"v":1,"job":` + good + `,"max_parallel_plugins":2,"command":"id"}`, proto.ReasonMalformed},
		{"unknown key in job", reqJSON(strings.Replace(good, `"kind"`, `"command":"id","kind"`, 1), "2"), proto.ReasonMalformed},
		{"unknown key in plugin", reqJSON(jobJSON(`[{"plugin_uuid":"`+pluginID+`","execute":"echo","timeout_s":5,"operator":"equals"}]`, ""), "2"), proto.ReasonMalformed},
		{"v 0", `{"v":0,"job":` + good + `,"max_parallel_plugins":2}`, proto.ReasonMalformed},
		{"v 2", `{"v":2,"job":` + good + `,"max_parallel_plugins":2}`, proto.ReasonMalformed},
		{"v string", `{"v":"1","job":` + good + `,"max_parallel_plugins":2}`, proto.ReasonMalformed},
		{"v 1.0", `{"v":1.0,"job":` + good + `,"max_parallel_plugins":2}`, proto.ReasonMalformed},
		{"v missing", `{"job":` + good + `,"max_parallel_plugins":2}`, proto.ReasonMalformed},
		{"mpp missing", `{"v":1,"job":` + good + `}`, proto.ReasonMalformed},
		{"mpp 0", reqJSON(good, "0"), proto.ReasonMalformed},
		{"mpp 9", reqJSON(good, "9"), proto.ReasonMalformed},
		{"mpp -1", reqJSON(good, "-1"), proto.ReasonMalformed},
		{"mpp string", reqJSON(good, `"2"`), proto.ReasonMalformed},
		{"mpp 1.5", reqJSON(good, "1.5"), proto.ReasonMalformed},
		{"mpp null", reqJSON(good, "null"), proto.ReasonMalformed},
		{"job missing", `{"v":1,"max_parallel_plugins":2}`, proto.ReasonMalformed},
		{"job null", reqJSON("null", "2"), proto.ReasonMalformed},
		{"inventory job", reqJSON(inv, "2"), proto.ReasonNotCompliance},
		{"0 plugins", reqJSON(jobJSON("[]", ""), "2"), proto.ReasonMalformed},
		{"5001 plugins", reqJSON(jobJSON(many(5001), ""), "2"), proto.ReasonMalformed},
		{"timeout 0", reqJSON(jobJSON(plugin("0"), ""), "2"), proto.ReasonMalformed},
		{"timeout 601", reqJSON(jobJSON(plugin("601"), ""), "2"), proto.ReasonMalformed},
		{"51 patterns", reqJSON(jobJSON("", `[`+strings.TrimSuffix(strings.Repeat(`"a",`, 51), ",")+`]`), "2"), proto.ReasonMalformed},
		{"two values", reqJSON(good, "2") + reqJSON(good, "2"), proto.ReasonMalformed},
		{"value then number", reqJSON(good, "2") + " 1", proto.ReasonMalformed},
		{"array", "[" + reqJSON(good, "2") + "]", proto.ReasonMalformed},
		{"bare string", `"run id"`, proto.ReasonMalformed},
		{"plugins without job", `{"v":1,"plugins":` + plugin("5") + `,"max_parallel_plugins":2}`, proto.ReasonMalformed},
		{"case-variant V", `{"V":1,"job":` + good + `,"max_parallel_plugins":2}`, proto.ReasonMalformed},
		{"case-variant Job", `{"v":1,"Job":` + good + `,"max_parallel_plugins":2}`, proto.ReasonMalformed},
		{"not json", `{"v":1,`, proto.ReasonMalformed},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			req, err := proto.ReadRequest(bytes.NewReader(frame([]byte(c.body))))
			if err == nil {
				t.Fatalf("accepted: %+v", req)
			}
			if !reflect.DeepEqual(req, proto.Request{}) {
				t.Errorf("non-zero request returned with an error")
			}
			if got := proto.RefusalFor(err); got != c.word {
				t.Errorf("RefusalFor = %q, want %q", got, c.word)
			}
		})
	}
	// Accepted at the bounds: 1 and 8 parallel, 5,000 plugins, 50 patterns,
	// an empty pattern list, uppercase UUIDs.
	accepted := []string{
		reqJSON(good, "1"), reqJSON(good, "8"),
		reqJSON(jobJSON(many(5000), ""), "2"),
		reqJSON(jobJSON("", `[`+strings.TrimSuffix(strings.Repeat(`"a",`, 50), ",")+`]`), "2"),
		reqJSON(jobJSON("", "[]"), "2"),
		reqJSON(strings.Replace(good, agentID, strings.ToUpper(agentID), 1), "2"),
	}
	for i, body := range accepted {
		if _, err := proto.ReadRequest(bytes.NewReader(frame([]byte(body)))); err != nil {
			t.Errorf("accepted case %d refused: %v", i, err)
		}
	}
	// WriteRequest refuses (and writes nothing for) what the runner refuses.
	for _, mpp := range []int{0, 9} {
		var buf bytes.Buffer
		if err := proto.WriteRequest(&buf, proto.Request{V: 1, Job: validJob(t), MaxParallelPlugins: mpp}); err == nil || buf.Len() != 0 {
			t.Errorf("WriteRequest mpp %d: err %v, wrote %d bytes", mpp, err, buf.Len())
		}
	}
	var buf bytes.Buffer
	if err := proto.WriteRequest(&buf, proto.Request{V: 2, Job: validJob(t), MaxParallelPlugins: 2}); err == nil || buf.Len() != 0 {
		t.Errorf("WriteRequest v 2: err %v, wrote %d", err, buf.Len())
	}
}

// sourceMap parses the package's non-test Go files.
func sourceMap(t *testing.T, mode parser.Mode) map[string]*ast.File {
	t.Helper()
	ents, err := os.ReadDir(".")
	if err != nil {
		t.Fatal(err)
	}
	out := map[string]*ast.File{}
	fset := token.NewFileSet()
	for _, e := range ents {
		n := e.Name()
		if e.IsDir() || !strings.HasSuffix(n, ".go") || strings.HasSuffix(n, "_test.go") {
			continue
		}
		src, err := fs.ReadFile(os.DirFS("."), n)
		if err != nil {
			t.Fatal(err)
		}
		f, err := parser.ParseFile(fset, n, src, mode)
		if err != nil {
			t.Fatal(err)
		}
		out[n] = f
	}
	if len(out) == 0 {
		t.Fatal("no source files")
	}
	return out
}

func sources(t *testing.T, mode parser.Mode) []*ast.File {
	t.Helper()
	m := sourceMap(t, mode)
	var out []*ast.File
	for _, k := range slices.Sorted(maps.Keys(m)) {
		out = append(out, m[k])
	}
	return out
}

func leftPad(i int) string { return fmt.Sprintf("%012d", i) }

// Recorded, not asserted (plan CHK-M10-003): invalid UTF-8 inside a string,
// duplicate keys and trailing whitespace.
func TestRequestRecordedCases(t *testing.T) {
	good := jobJSON("", "")
	for name, body := range map[string]string{
		"invalid utf-8 in execute": reqJSON(jobJSON(`[{"plugin_uuid":"`+pluginID+`","execute":"echo \xff","timeout_s":5}]`, ""), "2"),
		"duplicate v":              `{"v":1,"v":1,"job":` + good + `,"max_parallel_plugins":2}`,
		"trailing whitespace":      reqJSON(good, "2") + " \n",
	} {
		_, err := proto.ReadRequest(bytes.NewReader(frame([]byte(body))))
		t.Logf("RECORDED %s: accepted=%v", name, err == nil)
	}
}

// CHK-M10-004: frame bounds; an oversize header is refused after exactly 4
// bytes.
func TestFrameBounds(t *testing.T) {
	t.Run("request oversize", func(t *testing.T) {
		r := &failAfter{t: t, data: append(header(proto.MaxRequest+1), make([]byte, 64)...), limit: 4}
		if _, err := proto.ReadRequest(r); !errors.Is(err, proto.ErrFrame) {
			t.Fatalf("err %v, want ErrFrame", err)
		}
		if r.n != 4 {
			t.Fatalf("read %d bytes", r.n)
		}
	})
	t.Run("reply oversize", func(t *testing.T) {
		r := &failAfter{t: t, data: append(header(proto.MaxReply+1), make([]byte, 64)...), limit: 4}
		if _, err := proto.ReadReply(r); !errors.Is(err, proto.ErrFrame) {
			t.Fatalf("err %v, want ErrFrame", err)
		}
		if r.n != 4 {
			t.Fatalf("read %d bytes", r.n)
		}
	})
	t.Run("max uint32", func(t *testing.T) {
		r := &failAfter{t: t, data: header(0xFFFFFFFF), limit: 4}
		if _, err := proto.ReadRequest(r); !errors.Is(err, proto.ErrFrame) {
			t.Fatalf("err %v", err)
		}
	})
	if proto.MaxRequest != 33554432 || proto.MaxReply != 1048576 || proto.MaxStdout != 65536 || proto.MaxStderr != 16384 || proto.Version != 1 {
		t.Fatalf("constants: %d %d %d %d %d", proto.MaxRequest, proto.MaxReply, proto.MaxStdout, proto.MaxStderr, proto.Version)
	}
	t.Run("at the cap the body is read", func(t *testing.T) {
		// A request of exactly MaxRequest bytes: a valid request padded with
		// spaces is not compact, so use garbage and expect ErrMalformed (not
		// ErrFrame): the length itself was allowed.
		body := bytes.Repeat([]byte("x"), proto.MaxRequest)
		_, err := proto.ReadRequest(bytes.NewReader(frame(body)))
		if err == nil || errors.Is(err, proto.ErrFrame) || !errors.Is(err, proto.ErrMalformed) {
			t.Fatalf("err %v: want ErrMalformed, not ErrFrame", err)
		}
		rbody := bytes.Repeat([]byte("x"), proto.MaxReply)
		_, err = proto.ReadReply(bytes.NewReader(frame(rbody)))
		if err == nil || errors.Is(err, proto.ErrFrame) || !errors.Is(err, proto.ErrMalformed) {
			t.Fatalf("reply err %v: want ErrMalformed, not ErrFrame", err)
		}
	})
	t.Run("a large valid request near the cap", func(t *testing.T) {
		// 5,000 plugins with long commands: about 30 MiB, under the cap.
		var parts []string
		cmd := strings.Repeat("c", 6000)
		for i := range 5000 {
			parts = append(parts, `{"plugin_uuid":"00000000-0000-4000-8000-`+leftPad(i)+`","execute":"`+cmd+`","timeout_s":5}`)
		}
		body := []byte(reqJSON(jobJSON("["+strings.Join(parts, ",")+"]", ""), "2"))
		if len(body) > proto.MaxRequest || len(body) < 29<<20 {
			t.Fatalf("size %d", len(body))
		}
		if _, err := proto.ReadRequest(bytes.NewReader(frame(body))); err != nil {
			t.Fatalf("refused: %v", err)
		}
	})
	short := []struct {
		name string
		raw  []byte
	}{
		{"zero length", header(0)},
		{"two header bytes", []byte{0, 0}},
		{"truncated body", append(header(100), make([]byte, 50)...)},
	}
	for _, c := range short {
		t.Run(c.name, func(t *testing.T) {
			if _, err := proto.ReadRequest(bytes.NewReader(c.raw)); !errors.Is(err, proto.ErrFrame) {
				t.Errorf("request: err %v, want ErrFrame", err)
			}
			if _, err := proto.ReadReply(bytes.NewReader(c.raw)); !errors.Is(err, proto.ErrFrame) {
				t.Errorf("reply: err %v, want ErrFrame", err)
			}
		})
	}
	t.Run("clean EOF", func(t *testing.T) {
		_, err := proto.ReadReply(bytes.NewReader(nil))
		if err == nil || !errors.Is(err, io.EOF) {
			t.Fatalf("err %v, want io.EOF", err)
		}
	})
	t.Run("one frame only is read", func(t *testing.T) {
		var buf bytes.Buffer
		_ = proto.WriteReply(&buf, proto.Reply{Kind: proto.KindAccepted})
		_ = proto.WriteReply(&buf, proto.Reply{Kind: proto.KindDone})
		first := buf.Len()
		r := bytes.NewReader(buf.Bytes())
		rep, err := proto.ReadReply(r)
		if err != nil || rep.Kind != proto.KindAccepted {
			t.Fatal(rep, err)
		}
		if r.Len() != first-len(`{"type":"accepted"}`)-4 {
			t.Fatalf("read past the first frame: %d left of %d", r.Len(), first)
		}
	})
}

// CHK-M10-005: reply refusals.
func TestReplyRefusals(t *testing.T) {
	item := itemJSON(t, validItem())
	withKey := func(k string, v any) string {
		m := map[string]any{}
		for kk, vv := range item {
			m[kk] = vv
		}
		m[k] = v
		b, _ := json.Marshal(m)
		return string(b)
	}
	good, _ := json.Marshal(item)
	cases := map[string]string{
		"unknown type":             `{"type":"run"}`,
		"no type":                  `{}`,
		"accepted extra":           `{"type":"accepted","x":1}`,
		"accepted with reason":     `{"type":"accepted","reason":"busy"}`,
		"done extra":               `{"type":"done","result":{}}`,
		"refused unknown word":     `{"type":"refused","reason":"nope"}`,
		"refused empty word":       `{"type":"refused","reason":""}`,
		"refused without reason":   `{"type":"refused"}`,
		"refused extra":            `{"type":"refused","reason":"busy","detail":"x"}`,
		"result without result":    `{"type":"result"}`,
		"result extra":             `{"type":"result","result":` + string(good) + `,"x":1}`,
		"result item unknown key":  `{"type":"result","result":` + withKey("command", "id") + `}`,
		"result item bad error":    `{"type":"result","result":` + withKey("error", "timeout") + `}`,
		"case-variant Type":        `{"Type":"accepted"}`,
		"two values":               `{"type":"accepted"}{"type":"done"}`,
		"array":                    `[{"type":"accepted"}]`,
		"type number":              `{"type":1}`,
		"refused reason uppercase": `{"type":"refused","reason":"BUSY"}`,
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			if rep, err := proto.ReadReply(bytes.NewReader(frame([]byte(body)))); err == nil {
				t.Fatalf("accepted: %+v", rep)
			} else if !errors.Is(err, proto.ErrMalformed) {
				t.Errorf("err %v, want ErrMalformed", err)
			}
		})
	}
	// WriteReply refuses an unknown kind, an unknown word, and a zero Result.
	for _, rep := range []proto.Reply{
		{Kind: "run"}, {Kind: proto.KindRefused, Reason: "nope"}, {Kind: proto.KindRefused},
		{Kind: proto.KindResult},
	} {
		var buf bytes.Buffer
		if err := proto.WriteReply(&buf, rep); err == nil || buf.Len() != 0 {
			t.Errorf("WriteReply(%+v): err %v, wrote %d", rep, err, buf.Len())
		}
	}
}

// CHK-M10-006: result caps and error rules, by NewResult and by the reply
// decoder (frames built by hand).
func TestResultCaps(t *testing.T) {
	type tc struct {
		name string
		mod  func(*wire.ResultItem)
		ok   bool
	}
	cases := []tc{
		{"stdout 65536", func(i *wire.ResultItem) { i.Stdout = strings.Repeat("a", 65536) }, true},
		{"stdout 65537", func(i *wire.ResultItem) { i.Stdout = strings.Repeat("a", 65537) }, false},
		{"stdout 21845 euro + 1", func(i *wire.ResultItem) { i.Stdout = strings.Repeat("€", 21845) + "a" }, true},
		{"stdout 21845 euro + 2", func(i *wire.ResultItem) { i.Stdout = strings.Repeat("€", 21845) + "ab" }, false},
		{"stdout 16384 emoji", func(i *wire.ResultItem) { i.Stdout = strings.Repeat("😀", 16384) }, true},
		{"stdout 16384 emoji + 1", func(i *wire.ResultItem) { i.Stdout = strings.Repeat("😀", 16384) + "a" }, false},
		{"stderr 16384", func(i *wire.ResultItem) { i.Stderr = strings.Repeat("e", 16384) }, true},
		{"stderr 16385", func(i *wire.ResultItem) { i.Stderr = strings.Repeat("e", 16385) }, false},
		{"stderr 8192 e-acute + 1", func(i *wire.ResultItem) { i.Stderr = strings.Repeat("é", 8192) + "a" }, false},
		{"error runner_unavailable", func(i *wire.ResultItem) {
			i.Error, i.ExitCode, i.Stdout = ptr(wire.ErrRunnerUnavailable), nil, ""
		}, true},
		{"error spool_overflow", func(i *wire.ResultItem) {
			i.Error, i.ExitCode, i.Stdout = ptr(wire.ErrSpoolOverflow), nil, ""
		}, true},
		{"error timeout", func(i *wire.ResultItem) {
			i.Error, i.ExitCode, i.Stdout = ptr(wire.ResultError("timeout")), nil, ""
		}, false},
		{"error empty", func(i *wire.ResultItem) {
			i.Error, i.ExitCode, i.Stdout = ptr(wire.ResultError("")), nil, ""
		}, false},
		{"error with exit code", func(i *wire.ResultItem) {
			i.Error, i.Stdout = ptr(wire.ErrRunnerUnavailable), ""
		}, false},
		{"error with stdout", func(i *wire.ResultItem) { i.Error, i.ExitCode = ptr(wire.ErrSpoolOverflow), nil }, false},
		{"error with stderr", func(i *wire.ResultItem) {
			i.Error, i.ExitCode, i.Stdout, i.Stderr = ptr(wire.ErrSpoolOverflow), nil, "", "x"
		}, false},
		{"exit null no error", func(i *wire.ResultItem) { i.ExitCode = nil }, true},
		{"bad uuid", func(i *wire.ResultItem) { i.PluginUUID = "x" }, false},
		{"U+0000 kept", func(i *wire.ResultItem) { i.Stdout = "a\x00b" }, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			it := validItem()
			c.mod(&it)
			_, err := proto.NewResult(it)
			if (err == nil) != c.ok {
				t.Errorf("NewResult ok=%v, want %v (err %v)", err == nil, c.ok, err)
			}
			b, merr := json.Marshal(map[string]any{"type": "result", "result": it})
			if merr != nil {
				t.Fatal(merr)
			}
			_, err = proto.ReadReply(bytes.NewReader(frame(b)))
			if (err == nil) != c.ok {
				t.Errorf("ReadReply ok=%v, want %v (err %v)", err == nil, c.ok, err)
			}
		})
	}
	// Invalid UTF-8 is refused by NewResult (json.Marshal would hide it, so
	// it is checked on NewResult only).
	it := validItem()
	it.Stdout = "a\xffb"
	if _, err := proto.NewResult(it); err == nil {
		t.Error("NewResult accepted invalid UTF-8 stdout")
	}
	it = validItem()
	it.Stderr = "\xc3"
	if _, err := proto.NewResult(it); err == nil {
		t.Error("NewResult accepted invalid UTF-8 stderr")
	}
	// A maximal valid item fits a reply frame.
	it = validItem()
	it.Stdout = strings.Repeat("\x01", 65536)
	it.Stderr = strings.Repeat("\x01", 16384)
	r, err := proto.NewResult(it)
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	if err := proto.WriteReply(&buf, proto.Reply{Kind: proto.KindResult, Result: r}); err != nil {
		t.Fatalf("maximal item not sendable: %v", err)
	}
	if _, err := proto.ReadReply(&buf); err != nil {
		t.Fatalf("maximal item not readable: %v", err)
	}
}

// CHK-M10-007: Result has no exported field; Item returns a copy.
func TestResultEncapsulation(t *testing.T) {
	rt := reflect.TypeFor[proto.Result]()
	for i := range rt.NumField() {
		if rt.Field(i).IsExported() {
			t.Errorf("Result has exported field %s", rt.Field(i).Name)
		}
	}
	it := validItem()
	it.ExitCode = ptr(int64(5))
	r, err := proto.NewResult(it)
	if err != nil {
		t.Fatal(err)
	}
	*it.ExitCode = 9 // the input is copied
	got := r.Item()
	*got.ExitCode = 7
	got.Stdout = "changed"
	again := r.Item()
	if *again.ExitCode != 5 || again.Stdout != "install ok installed" {
		t.Fatalf("Result changed through a copy: %+v exit %d", again, *again.ExitCode)
	}
	e := validItem()
	e.ExitCode, e.Stdout, e.Error = nil, "", ptr(wire.ErrSpoolOverflow)
	r2, err := proto.NewResult(e)
	if err != nil {
		t.Fatal(err)
	}
	g2 := r2.Item()
	*g2.Error = wire.ErrRunnerUnavailable
	if *r2.Item().Error != wire.ErrSpoolOverflow {
		t.Fatal("error pointer shared")
	}
	// The zero Result cannot be sent (#130 (i)).
	var buf bytes.Buffer
	if err := proto.WriteReply(&buf, proto.Reply{Kind: proto.KindResult, Result: proto.Result{}}); err == nil {
		t.Fatal("zero Result sent")
	}
}

// CHK-M10-008: the #131 (b) and #140 items.
func TestUnavailableAndOverflow(t *testing.T) {
	now := time.Date(2026, 10, 30, 9, 15, 30, 123000000, time.FixedZone("X", 3600))
	u := proto.UnavailableResult(pluginID, now).Item()
	if u.PluginUUID != pluginID || u.ExitCode != nil || u.Stdout != "" || u.Stderr != "" || u.TimedOut || u.Truncated ||
		u.Error == nil || *u.Error != wire.ErrRunnerUnavailable || !u.StartedAt.Time().Equal(now) || !u.FinishedAt.Time().Equal(now) {
		t.Fatalf("unavailable item %+v", u)
	}
	m := itemJSON(t, u)
	if m["started_at"] != m["finished_at"] || !strings.HasSuffix(m["started_at"].(string), "Z") {
		t.Fatalf("times %v %v (want equal, UTC Z)", m["started_at"], m["finished_at"])
	}
	if _, err := proto.NewResult(u); err != nil {
		t.Fatalf("unavailable item fails NewResult: %v", err)
	}
	src := validItem()
	src.Stdout = strings.Repeat("s", 65536)
	src.Stderr = "err"
	src.ExitCode = ptr(int64(1))
	src.TimedOut, src.Truncated = true, true
	full, err := proto.NewResult(src)
	if err != nil {
		t.Fatal(err)
	}
	o := proto.OverflowMarker(full).Item()
	if o.PluginUUID != src.PluginUUID || o.ExitCode != nil || o.Stdout != "" || o.Stderr != "" || o.TimedOut || o.Truncated ||
		o.Error == nil || *o.Error != wire.ErrSpoolOverflow {
		t.Fatalf("marker %+v", o)
	}
	om, sm := itemJSON(t, o), itemJSON(t, src)
	if om["started_at"] != sm["started_at"] || om["finished_at"] != sm["finished_at"] {
		t.Fatalf("marker times %v %v, want %v %v", om["started_at"], om["finished_at"], sm["started_at"], sm["finished_at"])
	}
	if _, err := proto.NewResult(o); err != nil {
		t.Fatalf("marker fails NewResult: %v", err)
	}
	// Both keep exactly the nine Results keys.
	keys := slices.Sorted(func(yield func(string) bool) {
		for k := range om {
			if !yield(k) {
				return
			}
		}
	})
	want := []string{"error", "exit_code", "finished_at", "plugin_uuid", "started_at", "stderr", "stdout", "timed_out", "truncated"}
	if !slices.Equal(keys, want) {
		t.Fatalf("keys %v", keys)
	}
}

// CHK-M10-009: API listing over the package source.
func TestNoCommandAPI(t *testing.T) {
	files := sources(t, 0)
	forbidden := map[string]bool{"string": true, "[]string": true, "[]byte": true, "...string": true, "rune": true, "[]rune": true}
	exprString := func(e ast.Expr) string {
		switch v := e.(type) {
		case *ast.Ident:
			return v.Name
		case *ast.ArrayType:
			if id, ok := v.Elt.(*ast.Ident); ok {
				return "[]" + id.Name
			}
		case *ast.Ellipsis:
			if id, ok := v.Elt.(*ast.Ident); ok {
				return "..." + id.Name
			}
		case *ast.SelectorExpr:
			if x, ok := v.X.(*ast.Ident); ok {
				return x.Name + "." + v.Sel.Name
			}
		case *ast.StarExpr:
			return "*"
		}
		return "?"
	}
	var funcs []string
	{
		for _, f := range files {
			for _, d := range f.Decls {
				switch d := d.(type) {
				case *ast.FuncDecl:
					if !d.Name.IsExported() {
						continue
					}
					if d.Recv != nil {
						// Methods on unexported receivers are not API.
						rs := exprString(d.Recv.List[0].Type)
						if rs != "*" && !ast.IsExported(rs) {
							continue
						}
					}
					funcs = append(funcs, d.Name.Name)
					for _, fld := range d.Type.Params.List {
						ts := exprString(fld.Type)
						if forbidden[ts] {
							t.Errorf("exported %s takes a %s parameter", d.Name.Name, ts)
						}
						// Named string types allowed only if they are wire ids
						// or this package's word types.
						if strings.HasPrefix(ts, "wire.") && ts != "wire.UUID" && ts != "wire.Job" && ts != "wire.ResultItem" {
							t.Errorf("exported %s takes %s", d.Name.Name, ts)
						}
					}
				case *ast.GenDecl:
					for _, s := range d.Specs {
						ts, ok := s.(*ast.TypeSpec)
						if !ok || !ts.Name.IsExported() {
							continue
						}
						st, ok := ts.Type.(*ast.StructType)
						if !ok {
							continue
						}
						for _, fld := range st.Fields.List {
							for _, n := range fld.Names {
								if n.IsExported() && forbidden[exprString(fld.Type)] {
									t.Errorf("exported %s.%s is %s", ts.Name.Name, n.Name, exprString(fld.Type))
								}
							}
						}
					}
				}
			}
		}
	}
	sort.Strings(funcs)
	t.Logf("exported functions and methods: %v", funcs)
	rt := reflect.TypeFor[proto.Request]()
	var names []string
	for i := range rt.NumField() {
		names = append(names, rt.Field(i).Name+":"+rt.Field(i).Type.String())
	}
	if want := []string{"V:int", "Job:wire.Job", "MaxParallelPlugins:int"}; !slices.Equal(names, want) {
		t.Fatalf("Request fields %v, want %v", names, want)
	}
	rep := reflect.TypeFor[proto.Reply]()
	for i := range rep.NumField() {
		if rep.Field(i).Type.Kind() == reflect.String && rep.Field(i).Type.PkgPath() != reflect.TypeFor[proto.Reply]().PkgPath() {
			t.Errorf("Reply field %s is a plain string", rep.Field(i).Name)
		}
	}
}

// CHK-M10-010: purity, the 13 words, and no input text in errors.
func TestPurityWordsAndErrors(t *testing.T) {
	{
		for name, f := range sourceMap(t, parser.ImportsOnly) {
			for _, imp := range f.Imports {
				path := strings.Trim(imp.Path.Value, `"`)
				if path == "bitscan.local/agent/internal/agent/wire" {
					continue
				}
				if strings.Contains(path, ".") || strings.HasPrefix(path, "os") || strings.HasPrefix(path, "syscall") ||
					strings.HasPrefix(path, "net") || path == "log" || path == "log/slog" || path == "unsafe" {
					t.Errorf("%s imports %s", name, path)
				}
			}
			if strings.Contains(name, "_linux") || strings.Contains(name, "_windows") {
				t.Errorf("platform file %s", name)
			}
		}
	}
	// Exported Reason constants are exactly the 13 words.
	var words []string
	{
		for _, f := range sources(t, 0) {
			for _, d := range f.Decls {
				gd, ok := d.(*ast.GenDecl)
				if !ok || gd.Tok != token.CONST {
					continue
				}
				for _, s := range gd.Specs {
					vs := s.(*ast.ValueSpec)
					if id, ok := vs.Type.(*ast.Ident); !ok || id.Name != "Reason" {
						continue
					}
					for i, n := range vs.Names {
						if n.IsExported() {
							words = append(words, strings.Trim(vs.Values[i].(*ast.BasicLit).Value, `"`))
						}
					}
				}
			}
		}
	}
	sort.Strings(words)
	want := slices.Clone(allWords)
	sort.Strings(want)
	if !slices.Equal(words, want) {
		t.Fatalf("Reason constants %v, want %v", words, want)
	}
	for _, w := range allWords {
		var buf bytes.Buffer
		if err := proto.WriteReply(&buf, proto.Reply{Kind: proto.KindRefused, Reason: proto.Reason(w)}); err != nil {
			t.Errorf("word %s not sendable", w)
		}
	}
	// Errors carry no input text.
	good := jobJSON("", "")
	bodies := []string{
		`{"v":1,"job":` + good + `,"max_parallel_plugins":2,"` + canary + `":1}`,
		`{"v":1,"job":` + strings.Replace(good, "dpkg-query", canary+"\"", 1) + `,"max_parallel_plugins":2}`,
		`{"v":"` + canary + `"}`,
		canary,
	}
	for _, b := range bodies {
		_, err := proto.ReadRequest(bytes.NewReader(frame([]byte(b))))
		if err == nil {
			t.Fatalf("accepted %q", b)
		}
		if strings.Contains(err.Error(), canary) || strings.Contains(err.Error(), "M10CANARY") {
			t.Errorf("error quotes input: %v", err)
		}
	}
	for _, b := range []string{`{"type":"` + canary + `"}`, `{"type":"refused","reason":"` + canary + `"}`, canary} {
		_, err := proto.ReadReply(bytes.NewReader(frame([]byte(b))))
		if err == nil || strings.Contains(err.Error(), "M10CANARY") {
			t.Errorf("reply error %v", err)
		}
	}
	it := validItem()
	it.Stdout = strings.Repeat(canary, 10000)
	if _, err := proto.NewResult(it); err == nil || strings.Contains(err.Error(), "M10CANARY") {
		t.Errorf("NewResult error %v", err)
	}
}
