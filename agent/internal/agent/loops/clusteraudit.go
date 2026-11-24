package loops

import (
	"bytes"
	"compress/gzip"
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"bitscan.local/agent/internal/agent/cmaxclient"
	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/redact"
	"bitscan.local/agent/internal/runner/proto"
	"bitscan.local/agent/internal/spool"
)

// Auditor runs one ClusterMAX audit through cmax-helper; *cmaxclient.Client.
type Auditor interface {
	Audit(ctx context.Context, req cmaxclient.Request, kubeconfig []byte, onFile func(cmaxclient.FileInfo, []byte) error) (cmaxclient.Answer, error)
}

// ClusterAudit is the cluster_audit job handler (TS §3.8; owner decision
// 2026-11-23). It fetches the job's kubeconfig once (kept in memory only),
// asks cmax-helper for the one fixed audit, redacts the report and files,
// spools one result per check plus the run summary, and uploads the four
// files. It never runs a command itself and never judges PASS/FAIL.
type ClusterAudit struct {
	Run     *Run
	Spool   *spool.Spool
	Sender  *Sender
	Auditor Auditor
}

// auditFile is one redacted, gzip-compressed file waiting for upload.
type auditFile struct {
	name      string
	gz        []byte
	truncated bool
}

// Handle runs one accepted cluster_audit job.
func (c *ClusterAudit) Handle(ctx context.Context, job wire.Job) {
	r := c.Run
	cm := job.Cmax
	deadline := r.Clock().Now().Add(cmaxclient.AuditLimit)
	ids := make([]wire.UUID, len(cm.Checks))
	for i, ch := range cm.Checks {
		ids[i] = ch.PluginUUID
	}
	if err := c.Spool.StartJob(job.JobID, ids); err != nil {
		r.Log().Error("the cluster_audit job could not be recorded in the spool; not run", "job_id", string(job.JobID))
		r.SetLastError("spool: cluster_audit job not recorded")
		return
	}
	c.Sender.Wake() // the start notice (TS §3.3)
	set, err := redact.Compile(job.RedactionPatterns)
	var ans cmaxclient.Answer
	var report, runLog string
	var files []auditFile
	switch {
	case err != nil:
		err = &cmaxclient.Failure{Word: "redaction patterns refused"}
	default:
		ans, err = c.audit(ctx, job, set, &report, &runLog, &files)
	}
	if ctx.Err() != nil {
		return // left unfinished: no final batch (#131 (d))
	}
	var f *cmaxclient.Failure
	if err != nil && !errors.As(err, &f) {
		f = &cmaxclient.Failure{Word: "broken"}
	}
	c.spoolRun(job, set, ans, f, report, runLog)
	c.Sender.Wake()
	c.upload(ctx, job.JobID, files, deadline)
}

// audit fetches the kubeconfig when the job has one, runs the audit and
// keeps the redacted files. The kubeconfig bytes are cleared when it returns.
func (c *ClusterAudit) audit(ctx context.Context, job wire.Job, set *redact.Set, report, runLog *string, files *[]auditFile) (cmaxclient.Answer, error) {
	r := c.Run
	cm := job.Cmax
	var kube []byte
	if cm.Kubeconfig {
		resp, _ := r.Call(ctx, transport.Request{Op: transport.OpKubeconfig, JobID: job.JobID})
		defer clear(resp.Body)
		var ka struct {
			Kubeconfig string `json:"kubeconfig" wire:"min=1,max=1048576"`
		}
		if resp.Class != transport.Success || wire.DecodeStrict(resp.Body, &ka) != nil {
			return cmaxclient.Answer{}, &cmaxclient.Failure{Word: "kubeconfig not fetched"}
		}
		kube = []byte(ka.Kubeconfig)
		defer clear(kube)
	}
	req := cmaxclient.Request{JobID: job.JobID, Target: cm.Target, Vars: cm.Vars.Map()}
	return c.Auditor.Audit(ctx, req, kube, func(fi cmaxclient.FileInfo, raw []byte) error {
		red, cut := set.ApplyFile(raw, cmaxclient.MaxFile)
		switch fi.Name {
		case "report.txt":
			*report = string(red)
		case "run.log":
			*runLog = string(red)
		}
		gz, err := gzipBytes(red)
		if err != nil {
			return err
		}
		*files = append(*files, auditFile{name: fi.Name, gz: gz, truncated: cut || fi.Truncated})
		return nil
	})
}

// spoolRun stores one result per check (exit code 0, TS §6.5) and the run
// summary, then finishes the job.
func (c *ClusterAudit) spoolRun(job wire.Job, set *redact.Set, ans cmaxclient.Answer, f *cmaxclient.Failure, report, runLog string) {
	r := c.Run
	now := wire.NewTime(r.Clock().Now())
	started, finished := ans.StartedAt, ans.FinishedAt
	exit := ans.ExitCode
	var errorLine string
	switch {
	case f != nil:
		started, finished, exit = now, now, -1
		errorLine = "cmax-helper: " + f.Word
	case exit != 0:
		errorLine = cmaxErrorLine(runLog, exit)
	}
	if set != nil && errorLine != "" {
		errorLine, _ = set.Apply(redact.Captured{Data: []byte(errorLine)}, redact.Stderr)
	}
	errorLine = capRunes(errorLine, 512)
	status := "failed " + strconv.FormatInt(exit, 10) + ": " + errorLine
	if f == nil && exit == 0 {
		secs := int64(finished.Time().Sub(started.Time()) / time.Second)
		status = fmt.Sprintf("ok %d %s", max(secs, 0), ans.CmaxVersion)
	}
	checks := parseCmaxChecks(report)
	zero := int64(0)
	lost := 0
	for _, ch := range job.Cmax.Checks {
		var text string
		switch ch.CheckID {
		case "header":
			text = parseCmaxHeader(report)
		case "status":
			text = status
		default:
			var ok bool
			if text, ok = checks[ch.CheckID]; !ok {
				text = "MISSING " + ch.CheckID + " is not in the ClusterMAX report"
			}
		}
		if set != nil {
			text, _ = set.Apply(redact.Captured{Data: []byte(text)}, redact.Stdout)
		}
		res, err := proto.NewResult(wire.ResultItem{
			PluginUUID: ch.PluginUUID, ExitCode: &zero, Stdout: text, Stderr: "",
			StartedAt: started, FinishedAt: finished,
		})
		if err != nil {
			res = proto.UnavailableResult(ch.PluginUUID, r.Clock().Now())
		}
		if err := c.Spool.Put(job.JobID, res); err != nil {
			if c.Spool.Put(job.JobID, proto.OverflowMarker(res)) != nil {
				lost++
			}
		}
	}
	if lost > 0 {
		r.Log().Error("results could not be spooled, not even as markers", "job_id", string(job.JobID), "count", lost)
		r.SetLastError("spool: results not kept")
	}
	run := wire.CmaxRun{ExitCode: exit, StartedAt: started, FinishedAt: finished}
	if errorLine != "" {
		run.ErrorLine = &errorLine
	}
	if err := c.Spool.FinishRun(job.JobID, run); err != nil {
		r.Log().Error("the cluster_audit job could not be marked finished in the spool", "job_id", string(job.JobID))
		_ = c.Spool.Finish(job.JobID)
	}
	if f != nil {
		r.Log().Warn("the ClusterMAX audit did not run", "job_id", string(job.JobID), "reason", f.Word)
		r.SetLastError("cluster_audit: " + f.Word)
	}
}

// upload sends each file once, gzip-compressed, retrying with back-off until
// the job deadline; the files are not spooled (TS §3.8).
func (c *ClusterAudit) upload(ctx context.Context, jobID wire.UUID, files []auditFile, deadline time.Time) {
	r := c.Run
	back := schedule.NewBackoff(r.Rand())
	for _, f := range files {
		for {
			resp, _ := r.Call(ctx, transport.Request{Op: transport.OpFile, JobID: jobID, Name: f.name, Body: f.gz, Truncated: f.truncated})
			if resp.Class == transport.Success || resp.Class == transport.Drop || resp.Class == transport.Stop {
				break
			}
			wait := back.Next()
			if r.Clock().Now().Add(wait).After(deadline) {
				r.Log().Warn("a ClusterMAX file was not uploaded before the job deadline", "job_id", string(jobID), "file", f.name)
				r.SetLastError("cluster_audit: file not uploaded")
				break
			}
			if schedule.Sleep(ctx, r.Clock(), wait) != nil {
				return
			}
		}
		back.Reset()
		if ctx.Err() != nil {
			return
		}
	}
}

func gzipBytes(b []byte) ([]byte, error) {
	var buf bytes.Buffer
	zw := gzip.NewWriter(&buf)
	if _, err := zw.Write(b); err != nil {
		return nil, fmt.Errorf("loops: gzip: %w", err)
	}
	if err := zw.Close(); err != nil {
		return nil, fmt.Errorf("loops: gzip: %w", err)
	}
	return buf.Bytes(), nil
}
