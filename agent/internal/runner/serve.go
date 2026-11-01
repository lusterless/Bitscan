package runner

import (
	"context"
	"log/slog"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"bitscan.local/agent/internal/runner/proto"
)

// Deadlines of #130 (f).
const (
	requestWait = 30 * time.Second
	replyWait   = 60 * time.Second
)

// Executor runs one checked request and emits one Result per plugin (plan
// TASK-209 §4). Run returns nil once the job has ended: every plugin
// emitted, ctx cancelled or emit failed. A non-nil error means the runner
// can no longer guarantee its cleanup (a failed sweep) and must exit.
type Executor interface {
	Run(ctx context.Context, req proto.Request, emit func(proto.Result) error) error
}

// Listener is where connections come from: *sdsock.Listener, which returns
// only peer-checked connections (TASK-217).
type Listener interface {
	Accept() (*net.UnixConn, error)
	Close() error
}

// Server is the runner's serve loop: one connection carries one request,
// and one job runs at a time (#130).
type Server struct {
	Listener Listener
	Checks   *Checks
	Exec     Executor
	Clock    func() time.Time
	Log      *slog.Logger

	busy  atomic.Bool
	fatal error
	once  sync.Once
}

// Serve accepts until ctx is done (it returns nil after the running job has
// ended) or an executor reports a fatal error (it returns that error).
func (s *Server) Serve(ctx context.Context) error {
	var wg sync.WaitGroup
	defer wg.Wait()
	stop := context.AfterFunc(ctx, func() { _ = s.Listener.Close() })
	defer stop()
	for {
		conn, err := s.Listener.Accept()
		if err != nil {
			wg.Wait()
			if s.fatal != nil {
				return s.fatal
			}
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		if !s.busy.CompareAndSwap(false, true) {
			// A second connection while a job runs: refused at once, its
			// request never read (#130 (g)).
			_ = s.reply(conn, proto.Reply{Kind: proto.KindRefused, Reason: proto.ReasonBusy})
			_ = conn.Close()
			continue
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer s.busy.Store(false)
			defer func() { _ = conn.Close() }()
			if err := s.handle(ctx, conn); err != nil {
				s.once.Do(func() { s.fatal = err; _ = s.Listener.Close() })
			}
		}()
	}
}

func (s *Server) reply(conn *net.UnixConn, rep proto.Reply) error {
	_ = conn.SetWriteDeadline(time.Now().Add(replyWait))
	return proto.WriteReply(conn, rep)
}

// handle serves one connection. Logs carry ids, words and counts only,
// never a command, a pattern or output.
func (s *Server) handle(ctx context.Context, conn *net.UnixConn) error {
	_ = conn.SetReadDeadline(time.Now().Add(requestWait))
	req, err := proto.ReadRequest(conn)
	if err != nil {
		reason := proto.RefusalFor(err)
		_ = s.reply(conn, proto.Reply{Kind: proto.KindRefused, Reason: reason})
		s.Log.Info("runner: request refused", "reason", string(reason))
		return nil
	}
	job := req.Job
	if reason, ok := s.Checks.Check(req, s.Clock()); !ok {
		_ = s.reply(conn, proto.Reply{Kind: proto.KindRefused, Reason: reason})
		s.Log.Info("runner: job refused", "job_id", string(job.JobID), "reason", string(reason))
		return nil
	}
	if s.reply(conn, proto.Reply{Kind: proto.KindAccepted}) != nil {
		return nil
	}
	s.Log.Info("runner: job accepted", "job_id", string(job.JobID), "agent_id", string(job.AgentID), "plugins", len(job.Plugins))
	jobCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	// The agent sends nothing after its request: any read return (a byte,
	// EOF or an error) means the connection ended, and cancels the job. A
	// second frame is never decoded (REQ-261).
	readDone := make(chan struct{})
	_ = conn.SetReadDeadline(time.Time{})
	go func() {
		defer close(readDone)
		var b [1]byte
		_, _ = conn.Read(b[:])
		cancel()
	}()
	defer func() { _ = conn.Close(); <-readDone }()
	var mu sync.Mutex
	sent := 0
	emit := func(r proto.Result) error {
		mu.Lock()
		defer mu.Unlock()
		if err := s.reply(conn, proto.Reply{Kind: proto.KindResult, Result: r}); err != nil {
			cancel()
			return err
		}
		sent++
		return nil
	}
	if err := s.Exec.Run(jobCtx, req, emit); err != nil {
		s.Log.Error("runner: job ended, cleanup failed", "job_id", string(job.JobID))
		return err
	}
	if jobCtx.Err() != nil {
		s.Log.Info("runner: job cancelled", "job_id", string(job.JobID), "results", sent)
		return nil
	}
	if err := s.reply(conn, proto.Reply{Kind: proto.KindDone}); err != nil {
		return nil
	}
	s.Log.Info("runner: job done", "job_id", string(job.JobID), "results", sent)
	return nil
}
