// TS §3.8, §6.5 (owner decision 2026-11-23): the cluster_audit handler with a
// fake cmax-helper, the real spool and the real results sender.
package loops_test

import (
	"bytes"
	"compress/gzip"
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/cmaxclient"
	"bitscan.local/agent/internal/agent/loops"
	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/state"
	"bitscan.local/agent/internal/agent/token"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/spool"
)

const kubeSecret = "token: kube-secret-canary"

// auditManager answers results, the kubeconfig fetch and file uploads.
type auditManager struct {
	mu    sync.Mutex
	calls []transport.Request
	kube  int // status of the kubeconfig fetch
}

func (m *auditManager) Do(_ context.Context, r transport.Request) (transport.Response, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.calls = append(m.calls, r)
	switch r.Op {
	case transport.OpKubeconfig:
		if m.kube != 200 {
			return transport.Response{Status: m.kube, Class: transport.Drop, Problem: wire.Problem{Type: "job_not_acceptable"}}, nil
		}
		return transport.Response{Status: 200, Class: transport.Success, Body: []byte(`{"kubeconfig":"apiVersion: v1\n` + kubeSecret + `\n"}`)}, nil
	case transport.OpFile:
		return transport.Response{Status: 201, Class: transport.Success, Body: []byte(`{}`)}, nil
	}
	return transport.Response{Status: 200, Class: transport.Success, Body: []byte(`{"accepted":0,"duplicates":0}`)}, nil
}

func (m *auditManager) ops(op transport.Op) []transport.Request {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []transport.Request
	for _, c := range m.calls {
		if c.Op == op {
			out = append(out, c)
		}
	}
	return out
}

// fakeAuditor plays cmax-helper: it returns the real report fixture.
type fakeAuditor struct {
	req  cmaxclient.Request
	kube string
	fail error
	exit int64
	log  string
}

func (f *fakeAuditor) Audit(_ context.Context, req cmaxclient.Request, kube []byte, onFile func(cmaxclient.FileInfo, []byte) error) (cmaxclient.Answer, error) {
	f.req, f.kube = req, string(kube)
	if f.fail != nil {
		return cmaxclient.Answer{}, f.fail
	}
	report, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "collector", "tests", "fixtures", "report-vm.txt"))
	if err != nil {
		return cmaxclient.Answer{}, err
	}
	files := map[string][]byte{
		"report.txt": report, "run.log": []byte(f.log + "\npassword=hunter2\n"),
		"audit.out": []byte("audit"), "audit.values.json": []byte("{}"),
	}
	ans := cmaxclient.Answer{
		ExitCode: f.exit, CmaxVersion: "0.3.0",
		StartedAt: wire.NewTime(time.Date(2026, 11, 23, 8, 0, 0, 0, time.UTC)), FinishedAt: wire.NewTime(time.Date(2026, 11, 23, 8, 20, 0, 0, time.UTC)),
	}
	for _, name := range transport.FileNames {
		fi := cmaxclient.FileInfo{Name: name, Size: int64(len(files[name]))}
		ans.Files = append(ans.Files, fi)
		if err := onFile(fi, files[name]); err != nil {
			return cmaxclient.Answer{}, err
		}
	}
	return ans, nil
}

var auditChecks = []wire.CmaxCheck{
	{PluginUUID: "10000000-0000-4000-8000-000000000001", CheckID: "header"},
	{PluginUUID: "10000000-0000-4000-8000-000000000002", CheckID: "status"},
	{PluginUUID: "10000000-0000-4000-8000-000000000003", CheckID: "access.sudoAvailable"},
	{PluginUUID: "10000000-0000-4000-8000-000000000004", CheckID: "access.slurmCommandsOk"},
	{PluginUUID: "10000000-0000-4000-8000-000000000005", CheckID: "bmc-ipmi"},
	{PluginUUID: "10000000-0000-4000-8000-000000000006", CheckID: "not.in.report"},
}

func auditJob(kube bool) wire.Job {
	dra := "1"
	target := "auto"
	if kube {
		target = "k8s"
	}
	return wire.Job{
		JobID: "20000000-0000-4000-8000-000000000001", AgentID: agentID, Kind: wire.KindClusterAudit,
		PickupBy: wire.NewTime(time.Now().Add(time.Hour)),
		Cmax:     &wire.CmaxJob{Target: target, Kubeconfig: kube, Vars: wire.CmaxVars{GPUDRA: &dra}, Checks: auditChecks},
		// TS §8.6 key=value pattern: the run log's password is redacted.
		RedactionPatterns: []string{`(?i)(password)\s*[=:]\s*\S+`},
	}
}

// runAudit handles job and returns the manager once the final batch is posted.
func runAudit(t *testing.T, job wire.Job, aud *fakeAuditor, m *auditManager) []wire.ResultsRequest {
	t.Helper()
	dir := t.TempDir()
	sp, _, err := spool.Open(filepath.Join(dir, "spool"), 50<<20, time.Now)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = sp.Close() })
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	run := loops.NewRun(ctx, loops.Deps{
		Client: m, Tokens: token.NewHolder(state.Token{Value: canaryTok}), Rotator: &fakeRotator{},
		AgentID: agentID, Version: version, Clock: schedule.RealClock{}, Rand: half{},
		Log: newLogger(&logBuf{}), JobPullSeconds: 60, MaxParallelPlugins: 1,
	})
	sender := loops.NewSender(run, sp)
	go sender.Loop()
	(&loops.ClusterAudit{Run: run, Spool: sp, Sender: sender, Auditor: aud}).Handle(ctx, job)
	deadline := time.Now().Add(60 * time.Second)
	for {
		var posts []wire.ResultsRequest
		for _, r := range m.ops(transport.OpResults) {
			posts = append(posts, resultsOf(t, r))
		}
		if n := len(posts); n > 0 && posts[n-1].Final {
			return posts
		}
		if time.Now().After(deadline) {
			t.Fatalf("no final batch; %d posts", len(posts))
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func stdoutByPlugin(posts []wire.ResultsRequest) map[wire.UUID]string {
	out := map[wire.UUID]string{}
	for _, p := range posts {
		for _, it := range p.Results {
			out[it.PluginUUID] = it.Stdout
		}
	}
	return out
}

func gunzipString(t *testing.T, b []byte) string {
	t.Helper()
	zr, err := gzip.NewReader(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	raw, err := io.ReadAll(zr)
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

func TestClusterAuditResultsRunAndFiles(t *testing.T) {
	m := &auditManager{kube: 200}
	aud := &fakeAuditor{}
	posts := runAudit(t, auditJob(true), aud, m)
	if aud.req.Target != "k8s" || aud.req.Vars["CLUSTERMAX_K8S_GPU_DRA"] != "1" || len(aud.req.Vars) != 1 || !strings.Contains(aud.kube, kubeSecret) {
		t.Fatalf("helper request %+v kube %q", aud.req, aud.kube)
	}
	if len(m.ops(transport.OpKubeconfig)) != 1 {
		t.Fatal("kubeconfig not fetched exactly once")
	}
	got := stdoutByPlugin(posts)
	want := map[wire.UUID]string{
		auditChecks[1].PluginUUID: "ok 1200 0.3.0",
		auditChecks[5].PluginUUID: "MISSING not.in.report is not in the ClusterMAX report",
	}
	for id, w := range want {
		if got[id] != w {
			t.Errorf("%s: %q, want %q", id, got[id], w)
		}
	}
	if !strings.HasPrefix(got[auditChecks[0].PluginUUID], "Command: cmax audit; Target: Local virtual machine") ||
		!strings.HasPrefix(got[auditChecks[2].PluginUUID], "PASS observed=true\nPasswordless sudo") ||
		!strings.HasPrefix(got[auditChecks[3].PluginUUID], "n/a observed=n/a for standalone machines") ||
		strings.Contains(got[auditChecks[4].PluginUUID], "References") || strings.Contains(got[auditChecks[4].PluginUUID], "https://") {
		t.Errorf("parsed results %q", got)
	}
	final := posts[len(posts)-1]
	if final.CmaxRun == nil || final.CmaxRun.ExitCode != 0 || final.CmaxRun.ErrorLine != nil {
		t.Fatalf("cmax_run %+v", final.CmaxRun)
	}
	for _, p := range posts[:len(posts)-1] {
		if p.CmaxRun != nil {
			t.Fatal("cmax_run outside the final batch")
		}
	}
	files := m.ops(transport.OpFile)
	if len(files) != 4 {
		t.Fatalf("%d uploads", len(files))
	}
	for i, f := range files {
		if f.Name != transport.FileNames[i] {
			t.Errorf("upload %d is %s", i, f.Name)
		}
		body := gunzipString(t, f.Body)
		if strings.Contains(body, "hunter2") || strings.Contains(body, "kube-secret-canary") {
			t.Errorf("%s holds a secret", f.Name)
		}
	}
	if !strings.Contains(gunzipString(t, files[1].Body), "[REDACTED]") {
		t.Error("run.log not redacted")
	}
}

func TestClusterAuditFailedRun(t *testing.T) {
	m := &auditManager{}
	posts := runAudit(t, auditJob(false), &fakeAuditor{exit: 2, log: "cmax: error: no cluster found"}, m)
	if len(m.ops(transport.OpKubeconfig)) != 0 {
		t.Fatal("kubeconfig fetched for a job without one")
	}
	final := posts[len(posts)-1]
	if final.CmaxRun == nil || final.CmaxRun.ExitCode != 2 || final.CmaxRun.ErrorLine == nil || *final.CmaxRun.ErrorLine != "cmax: error: no cluster found" {
		t.Fatalf("cmax_run %+v", final.CmaxRun)
	}
	if s := stdoutByPlugin(posts)[auditChecks[1].PluginUUID]; s != "failed 2: cmax: error: no cluster found" {
		t.Fatalf("status %q", s)
	}
}

func TestClusterAuditHelperOrKubeconfigUnavailable(t *testing.T) {
	for name, tc := range map[string]struct {
		m    *auditManager
		aud  *fakeAuditor
		job  wire.Job
		word string
	}{
		"busy":       {&auditManager{}, &fakeAuditor{fail: &cmaxclient.Failure{Word: "busy"}}, auditJob(false), "cmax-helper: busy"},
		"kubeconfig": {&auditManager{kube: 409}, &fakeAuditor{}, auditJob(true), "cmax-helper: kubeconfig not fetched"},
	} {
		t.Run(name, func(t *testing.T) {
			posts := runAudit(t, tc.job, tc.aud, tc.m)
			final := posts[len(posts)-1]
			if final.CmaxRun == nil || final.CmaxRun.ExitCode != -1 || *final.CmaxRun.ErrorLine != tc.word {
				t.Fatalf("cmax_run %+v", final.CmaxRun)
			}
			got := stdoutByPlugin(posts)
			if got[auditChecks[1].PluginUUID] != "failed -1: "+tc.word || !strings.HasPrefix(got[auditChecks[2].PluginUUID], "MISSING ") {
				t.Fatalf("results %q", got)
			}
			if len(tc.m.ops(transport.OpFile)) != 0 {
				t.Fatal("files uploaded without a run")
			}
		})
	}
}
