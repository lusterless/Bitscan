// TP-M10-06 (tester-m10): the runner's job checks, REQ-236, REQ-244; #132.
// Internal test (package runner) so the 100,000-id bound can be reached by
// filling the seen set directly. Expected words come from #130 (d) and the
// #132 (e) order, not from the implementation. Pure: Windows and Linux.
package runner

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

const (
	ownID     = "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"
	foreignID = "11111111-2222-4333-8444-555555555555"
)

var now0 = time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)

func agentFile(t *testing.T, content string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "agent_id")
	if err := os.WriteFile(p, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func jobN(n int) wire.UUID { return wire.UUID(fmt.Sprintf("cccccccc-0000-4000-8000-%012d", n)) }

func plugins(n int) []wire.PluginSpec {
	out := make([]wire.PluginSpec, n)
	for i := range out {
		out[i] = wire.PluginSpec{PluginUUID: wire.UUID(fmt.Sprintf("abcdef00-0000-4000-8000-%012d", i+1)), Execute: "true", TimeoutS: 30}
	}
	return out
}

func req(id wire.UUID, mod func(*proto.Request)) proto.Request {
	r := proto.Request{V: 1, MaxParallelPlugins: 2, Job: wire.Job{
		JobID: id, AgentID: ownID, Kind: wire.KindCompliance, PickupBy: wire.NewTime(now0.Add(time.Hour)),
		Plugins: plugins(3), RedactionPatterns: []string{},
	}}
	if mod != nil {
		mod(&r)
	}
	return r
}

func at(d time.Duration) func(*proto.Request) {
	return func(r *proto.Request) { r.Job.PickupBy = wire.NewTime(now0.Add(d)) }
}

// CHK-M10-035: REQ-236 (1) refusals, each with its #130 word.
func TestChecksRefusals(t *testing.T) {
	file := agentFile(t, ownID+"\n")
	cases := []struct {
		name string
		mod  func(*proto.Request)
		want proto.Reason
	}{
		{"foreign agent_id", func(r *proto.Request) { r.Job.AgentID = foreignID }, proto.ReasonForeignAgent},
		{"pickup_by = now", at(0), proto.ReasonPickupPassed},
		{"pickup_by = now - 1 s", at(-time.Second), proto.ReasonPickupPassed},
		{"pickup_by = now + 25 h + 1 s", at(25*time.Hour + time.Second), proto.ReasonPickupTooFar},
		{"inventory job", func(r *proto.Request) {
			r.Job.Kind = wire.KindInventory
			r.Job.Plugins = nil
			r.Job.RedactionPatterns = nil
		}, proto.ReasonNotCompliance},
		{"0 plugins", func(r *proto.Request) { r.Job.Plugins = nil }, proto.ReasonBadPlugins},
		{"5,001 plugins", func(r *proto.Request) { r.Job.Plugins = plugins(5001) }, proto.ReasonBadPlugins},
		{"duplicate plugin_uuid", func(r *proto.Request) { r.Job.Plugins[2].PluginUUID = r.Job.Plugins[0].PluginUUID }, proto.ReasonBadPlugins},
		{"duplicate plugin_uuid in another case", func(r *proto.Request) {
			r.Job.Plugins[2].PluginUUID = wire.UUID(strings.ToUpper(string(r.Job.Plugins[0].PluginUUID)))
		}, proto.ReasonBadPlugins},
		{"timeout_s 0", func(r *proto.Request) { r.Job.Plugins[1].TimeoutS = 0 }, proto.ReasonBadPlugins},
		{"timeout_s 601", func(r *proto.Request) { r.Job.Plugins[1].TimeoutS = 601 }, proto.ReasonBadPlugins},
		{"max_parallel_plugins 0", func(r *proto.Request) { r.MaxParallelPlugins = 0 }, proto.ReasonBadParallel},
		{"max_parallel_plugins 9", func(r *proto.Request) { r.MaxParallelPlugins = 9 }, proto.ReasonBadParallel},
	}
	for i, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			ch := NewChecks(file)
			got, ok := ch.Check(req(jobN(i+1), c.mod), now0)
			if ok || got != c.want {
				t.Fatalf("got (%q, %v), want %q", got, ok, c.want)
			}
		})
	}
	// A missing, empty or malformed agent_id file.
	for name, path := range map[string]string{
		"missing":        filepath.Join(t.TempDir(), "nope"),
		"empty":          agentFile(t, ""),
		"non-UUID":       agentFile(t, "not-a-uuid\n"),
		"two LFs":        agentFile(t, ownID+"\n\n"),
		"CRLF":           agentFile(t, ownID+"\r\n"),
		"leading space":  agentFile(t, " "+ownID),
		"32-hex form":    agentFile(t, strings.ReplaceAll(ownID, "-", "")),
		"a directory":    t.TempDir(),
		"over 64 bytes":  agentFile(t, ownID+strings.Repeat(" ", 40)),
		"two ids":        agentFile(t, ownID+"\n"+ownID),
		"trailing tab":   agentFile(t, ownID+"\t"),
		"NUL after id":   agentFile(t, ownID+"\x00"),
		"braced form":    agentFile(t, "{"+ownID+"}"),
		"urn form":       agentFile(t, "urn:uuid:"+ownID),
		"hyphens moved":  agentFile(t, "6f1c2b3a4-d5e-4f60-8a7b-9c0d1e2f3a4b"),
		"only LF":        agentFile(t, "\n"),
		"id then LF LF?": agentFile(t, ownID+"\n "),
	} {
		t.Run("agent_id file "+name, func(t *testing.T) {
			got, ok := NewChecks(path).Check(req(jobN(900), nil), now0)
			if ok || got != proto.ReasonAgentIDUnreadable {
				t.Fatalf("got (%q, %v), want agent_id_unreadable", got, ok)
			}
		})
	}
}

// CHK-M10-036: accepted.
func TestChecksAccepts(t *testing.T) {
	for name, tc := range map[string]struct {
		file string
		mod  func(*proto.Request)
	}{
		"pickup_by = now + 25 h exactly": {ownID + "\n", at(25 * time.Hour)},
		"pickup_by = now + 1 ns":         {ownID + "\n", at(time.Nanosecond)},
		"uppercase agent_id in the job":  {ownID + "\n", func(r *proto.Request) { r.Job.AgentID = wire.UUID(strings.ToUpper(ownID)) }},
		"file without LF":                {ownID, nil},
		"uppercase file":                 {strings.ToUpper(ownID) + "\n", nil},
		"empty pattern list":             {ownID, func(r *proto.Request) { r.Job.RedactionPatterns = []string{} }},
		"1 and 600 s, 5,000 plugins": {ownID, func(r *proto.Request) {
			r.Job.Plugins = plugins(5000)
			r.Job.Plugins[0].TimeoutS = 1
			r.Job.Plugins[1].TimeoutS = 600
		}},
		"max_parallel 1":    {ownID, func(r *proto.Request) { r.MaxParallelPlugins = 1 }},
		"max_parallel 8":    {ownID, func(r *proto.Request) { r.MaxParallelPlugins = 8 }},
		"the five defaults": {ownID, func(r *proto.Request) { r.Job.RedactionPatterns = specDefaults(t) }},
	} {
		t.Run(name, func(t *testing.T) {
			if got, ok := NewChecks(agentFile(t, tc.file)).Check(req(jobN(1), tc.mod), now0); !ok {
				t.Fatalf("refused %q", got)
			}
		})
	}
}

func specDefaults(t *testing.T) []string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "docs", "spec", "Technical_Specification.md"))
	if err != nil {
		t.Fatal(err)
	}
	text := strings.ReplaceAll(string(raw), "\r\n", "\n")
	rest := text[strings.Index(text, "**Default redaction patterns**"):]
	block := rest[strings.Index(rest, "```text\n")+len("```text\n"):]
	lines := strings.Split(block[:strings.Index(block, "\n```")], "\n")
	if len(lines) != 5 {
		t.Fatalf("%d defaults", len(lines))
	}
	return lines
}

// CHK-M10-037: the #132 (e) order: kind → shape → patterns → agent_id →
// pickup_by → seen.
func TestChecksOrder(t *testing.T) {
	file := agentFile(t, ownID)
	bad := filepath.Join(t.TempDir(), "missing")
	cases := []struct {
		name string
		path string
		mod  func(*proto.Request)
		want proto.Reason
	}{
		{"inventory + bad parallel", file, func(r *proto.Request) { r.Job.Kind = wire.KindInventory; r.MaxParallelPlugins = 9 }, proto.ReasonNotCompliance},
		{"bad plugins + bad patterns", file, func(r *proto.Request) { r.Job.Plugins = nil; r.Job.RedactionPatterns = []string{"("} }, proto.ReasonBadPlugins},
		{"bad plugins + bad parallel", file, func(r *proto.Request) { r.Job.Plugins[0].TimeoutS = 0; r.MaxParallelPlugins = 0 }, proto.ReasonBadPlugins},
		{"bad parallel + bad patterns", file, func(r *proto.Request) { r.MaxParallelPlugins = 9; r.Job.RedactionPatterns = []string{"x*"} }, proto.ReasonBadParallel},
		{"bad patterns + foreign", file, func(r *proto.Request) { r.Job.RedactionPatterns = []string{"x*"}; r.Job.AgentID = foreignID }, proto.ReasonBadPatterns},
		{"bad patterns + unreadable file", bad, func(r *proto.Request) { r.Job.RedactionPatterns = []string{"("} }, proto.ReasonBadPatterns},
		{"unreadable file + expired", bad, at(-time.Hour), proto.ReasonAgentIDUnreadable},
		{"foreign + expired", file, func(r *proto.Request) { r.Job.AgentID = foreignID; at(-time.Hour)(r) }, proto.ReasonForeignAgent},
		{"foreign + too far", file, func(r *proto.Request) { r.Job.AgentID = foreignID; at(26 * time.Hour)(r) }, proto.ReasonForeignAgent},
	}
	for i, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, ok := NewChecks(c.path).Check(req(jobN(i+1), c.mod), now0)
			if ok || got != c.want {
				t.Fatalf("got (%q, %v), want %q", got, ok, c.want)
			}
		})
	}
	// expired + replayed → pickup_passed: the seen check comes last.
	ch := NewChecks(file)
	if _, ok := ch.Check(req(jobN(50), at(time.Minute)), now0); !ok {
		t.Fatal("first send refused")
	}
	if got, _ := ch.Check(req(jobN(50), at(time.Minute)), now0.Add(time.Minute)); got != proto.ReasonPickupPassed {
		t.Fatalf("expired replay: %q, want pickup_passed", got)
	}
}

// CHK-M10-038: REQ-236 (3) a refused id is recorded, so a corrected resend
// is replayed; and a plain replay.
func TestChecksRefusedIDRecorded(t *testing.T) {
	ch := NewChecks(agentFile(t, ownID))
	for k, mod := range []func(*proto.Request){
		func(r *proto.Request) { r.Job.AgentID = foreignID },
		func(r *proto.Request) { r.MaxParallelPlugins = 9 },
		func(r *proto.Request) { r.Job.RedactionPatterns = []string{"("} },
		at(26 * time.Hour),
	} {
		id := jobN(500 + k)
		if _, ok := ch.Check(req(id, mod), now0); ok {
			t.Fatal("bad request accepted")
		}
		if got, ok := ch.Check(req(id, nil), now0); ok || got != proto.ReasonReplayed {
			t.Fatalf("corrected resend: (%q, %v), want replayed", got, ok)
		}
	}
	if _, ok := ch.Check(req(jobN(7), nil), now0); !ok {
		t.Fatal("fresh id refused")
	}
	if got, ok := ch.Check(req(jobN(7), nil), now0); ok || got != proto.ReasonReplayed {
		t.Fatalf("replay: (%q, %v)", got, ok)
	}
	// An uppercase replay of the same id.
	if got, ok := ch.Check(req(wire.UUID(strings.ToUpper(string(jobN(7)))), nil), now0); ok || got != proto.ReasonReplayed {
		t.Fatalf("uppercase replay: (%q, %v)", got, ok)
	}
}

// CHK-M10-039: REQ-236 (4) expiry at pickup_by + 1 min and the 100,000 bound
// (Q2: a seen_full job is not recorded; once space frees it runs as a first
// run).
func TestChecksSeenBound(t *testing.T) {
	file := agentFile(t, ownID)
	ch := NewChecks(file)
	// Expiry: an id is forgotten at its pickup_by + 1 min. Probe it through
	// the map only (a resend after pickup_by is refused pickup_passed anyway).
	if _, ok := ch.Check(req(jobN(1), at(time.Hour)), now0); !ok {
		t.Fatal("refused")
	}
	until := now0.Add(time.Hour + time.Minute)
	ch.Check(req(jobN(2), at(2*time.Hour)), until.Add(-time.Nanosecond))
	ch.mu.Lock()
	_, still := ch.seen[jobN(1)]
	ch.mu.Unlock()
	if !still {
		t.Fatal("forgotten before pickup_by + 1 min")
	}
	ch.Check(req(jobN(3), at(3*time.Hour)), until)
	ch.mu.Lock()
	_, still = ch.seen[jobN(1)]
	ch.mu.Unlock()
	if still {
		t.Fatal("still remembered at pickup_by + 1 min")
	}
	// The bound: fill to 99,999 directly, then one more through Check, then
	// the next is seen_full.
	full := NewChecks(file)
	full.mu.Lock()
	for i := range MaxSeen - 1 {
		full.seen[jobN(100000+i)] = now0.Add(2 * time.Hour)
	}
	full.mu.Unlock()
	if _, ok := full.Check(req(jobN(1), at(time.Hour)), now0); !ok {
		t.Fatal("the 100,000th id refused")
	}
	if got, ok := full.Check(req(jobN(2), at(time.Hour)), now0); ok || got != proto.ReasonSeenFull {
		t.Fatalf("101st: (%q, %v), want seen_full", got, ok)
	}
	full.mu.Lock()
	_, rec := full.seen[jobN(2)]
	n := len(full.seen)
	full.mu.Unlock()
	if rec || n != MaxSeen {
		t.Fatalf("seen_full job recorded %v; size %d", rec, n)
	}
	// A refusal for another reason at the bound keeps its own word.
	if got, _ := full.Check(req(jobN(3), func(r *proto.Request) { r.Job.AgentID = foreignID }), now0); got != proto.ReasonForeignAgent {
		t.Fatalf("foreign at the bound: %q", got)
	}
	// Once the filled ids expire (at their +2 h), the seen_full job runs.
	if _, ok := full.Check(req(jobN(2), at(4*time.Hour)), now0.Add(2*time.Hour)); !ok {
		t.Fatal("the seen_full job was refused after space freed (Q2: it is a first run)")
	}
	if MaxSeen != 100000 {
		t.Fatalf("MaxSeen %d", MaxSeen)
	}
}

// CHK-M10-040: REQ-244 (1), (2) through the checks.
func TestChecksPatterns(t *testing.T) {
	file := agentFile(t, ownID)
	fifty1 := make([]string, 51)
	fifty := make([]string, 50)
	for i := range fifty1 {
		fifty1[i] = fmt.Sprint("p", i)
	}
	copy(fifty, fifty1)
	for i, bad := range [][]string{fifty1, {"("}, {"a{1001}"}, {`\C`}, {"x*"}, {"(?:)"}, {"a?"}, {`\b`}, {"^"}, {"ok", "x*"}} {
		got, ok := NewChecks(file).Check(req(jobN(i+1), func(r *proto.Request) { r.Job.RedactionPatterns = bad }), now0)
		if ok || got != proto.ReasonBadPatterns {
			t.Errorf("%q: (%q, %v), want bad_patterns", bad, got, ok)
		}
	}
	for i, good := range [][]string{fifty, specDefaults(t), {}} {
		if got, ok := NewChecks(file).Check(req(jobN(i+100), func(r *proto.Request) { r.Job.RedactionPatterns = good }), now0); !ok {
			t.Errorf("list %d refused %q", i, got)
		}
	}
}

// CHK-M10-041, CHK-M10-393: the agent_id file is read for every job.
func TestChecksReadsAgentIDPerJob(t *testing.T) {
	file := agentFile(t, ownID)
	ch := NewChecks(file)
	if _, ok := ch.Check(req(jobN(1), nil), now0); !ok {
		t.Fatal("refused")
	}
	if err := os.WriteFile(file, []byte(foreignID+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got, _ := ch.Check(req(jobN(2), nil), now0); got != proto.ReasonForeignAgent {
		t.Fatalf("after re-enrolment the old id was used: %q", got)
	}
	if got, ok := ch.Check(req(jobN(3), func(r *proto.Request) { r.Job.AgentID = foreignID }), now0); !ok {
		t.Fatalf("the new id refused: %q", got)
	}
	if err := os.Remove(file); err != nil {
		t.Fatal(err)
	}
	if got, _ := ch.Check(req(jobN(4), nil), now0); got != proto.ReasonAgentIDUnreadable {
		t.Fatalf("deleted file: %q", got)
	}
}

// CHK-M10-042: checks.go uses only the clock it is given, logs nothing and
// starts nothing (static).
func TestChecksStatic(t *testing.T) {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, "checks.go", nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	for _, imp := range f.Imports {
		p := strings.Trim(imp.Path.Value, `"`)
		if p == "os/exec" || p == "log" || p == "log/slog" || p == "net" || strings.HasPrefix(p, "golang.org/x/sys") {
			t.Errorf("checks.go imports %s", p)
		}
	}
	ast.Inspect(f, func(n ast.Node) bool {
		if sel, ok := n.(*ast.SelectorExpr); ok {
			if x, ok := sel.X.(*ast.Ident); ok && x.Name == "time" && (sel.Sel.Name == "Now" || sel.Sel.Name == "Since" || sel.Sel.Name == "Until") {
				t.Errorf("checks.go calls time.%s", sel.Sel.Name)
			}
		}
		return true
	})
}

// CHK-M10-043: concurrent checks of one new id: exactly one accepted.
func TestChecksConcurrentSameID(t *testing.T) {
	ch := NewChecks(agentFile(t, ownID))
	const n = 16
	var wg sync.WaitGroup
	start := make(chan struct{})
	results := make(chan proto.Reason, n)
	for range n {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			got, ok := ch.Check(req(jobN(1), nil), now0)
			if ok {
				got = "ok"
			}
			results <- got
		}()
	}
	close(start)
	wg.Wait()
	close(results)
	counts := map[proto.Reason]int{}
	for r := range results {
		counts[r]++
	}
	if counts["ok"] != 1 || counts[proto.ReasonReplayed] != n-1 {
		t.Fatalf("counts %v", counts)
	}
}
