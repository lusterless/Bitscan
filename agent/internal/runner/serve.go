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
// TASK-209 §4). Run returns nil once the job has ended and its own cleanup
// is done: every plugin emitted, ctx cancelled or emit failed. Idle is the
// cleanup for when no job runs (TS §3.5: the full sweep and the emptied
// private /tmp); Serve calls it after the last running job ends, with no
// job able to start meanwhile. A non-nil error from either means the runner
// can no longer guarantee its cleanup (a failed sweep) and must exit.
type Executor interface {
	Run(ctx context.Context, req proto.Request, emit func(proto.Result) error) error
	Idle(ctx context.Context) error
}

// DefaultMaxJobs is the most jobs the runner serves at once: the top of
// max_parallel_jobs (TS §3.7, owner decision 2026-11-14).
const DefaultMaxJobs = 4

// Listener is where connections come from: *sdsock.Listener, which returns
// only peer-checked connections (TASK-217).
type Listener interface {
	Accept() (*net.UnixConn, error)
	Close() error
}

// Server is the runner's serve loop: one connection carries one request
// (#130), and at most MaxJobs jobs run at once (TS §3.7).
type Server struct {
	Listener Listener
	Checks   *Checks
	Exec     Executor
	Clock    func() time.Time
	Log      *slog.Logger
	// MaxJobs is the most connections served at once; 0 means
	// DefaultMaxJobs. One more is refused busy, its request unread.
	MaxJobs int

	// mu guards active. The idle cleanup runs with mu held, so no job is
	// accepted while it sweeps.
	mu     sync.Mutex
	active int
	// failed is set, after fatal and before the slot is freed, once a
	// cleanup failed: no job may run after that (TASK-225 r1).
	failed atomic.Bool
	fatal  error
	once   sync.Once
}

// Active is the number of connections being served.
func (s *Server) Active() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.active
}

func (s *Server) maxJobs() int {
	if s.MaxJobs > 0 {
		return s.MaxJobs
	}
	return DefaultMaxJobs
}

// take reserves a slot; false when all are in use.
func (s *Server) take() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.active >= s.maxJobs() {
		return false
	}
	s.active++
	return true
}

// release frees a slot and closes the connection, both under mu. When it
// was the last slot and nothing has failed, the connection is closed and
// then the idle cleanup runs, still under mu: the client sees EOF at once,
// and a connection made meanwhile waits in take until the cleanup is done,
// so no job starts during it and none is refused busy for it. A failed idle
// cleanup is fatal like a failed job cleanup.
func (s *Server) release(ctx context.Context, conn *net.UnixConn) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.active--
	_ = conn.Close()
	if s.active == 0 && !s.failed.Load() {
		if err := s.Exec.Idle(context.WithoutCancel(ctx)); err != nil {
			s.Log.Error("runner: idle cleanup failed")
			s.fail(err)
		}
	}
}

func (s *Server) fail(err error) {
	s.once.Do(func() { s.fatal = err; s.failed.Store(true); _ = s.Listener.Close() })
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
			if s.failed.Load() {
				return s.fatal
			}
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		won := s.take()
		// Checked after take: failed is set before a slot is freed, so a
		// slot won after a fatal sees it; checked before, a fatal between the
		// check and take would let one job run after a failed sweep.
		// Closed unanswered: a busy reply would make the agent retry.
		if s.failed.Load() {
			if won {
				s.mu.Lock()
				s.active--
				s.mu.Unlock()
			}
			_ = conn.Close()
			wg.Wait()
			return s.fatal
		}
		if !won {
			// One connection more than MaxJobs: refused at once, its request
			// never read (#130 (g)).
			_ = s.reply(conn, proto.Reply{Kind: proto.KindRefused, Reason: proto.ReasonBusy})
			_ = conn.Close()
			continue
		}
		wg.Add(1)
		go func() {
			// In this order (TASK-225 r1): handle has ended the job and its
			// cleanup, and a fatal error has set failed and closed the
			// listener; then, under mu, the slot is freed and the connection
			// closed, so a client that sees EOF and dials again is served
			// (after the idle cleanup when this was the last job); wg.Done
			// last, so Serve waits for it.
			defer func() {
				s.release(ctx, conn)
				wg.Done()
			}()
			if err := s.handle(ctx, conn); err != nil {
				s.fail(err)
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
	// The reader is woken by a past read deadline (it applies to a pending
	// Read too), not by a close: Serve closes the connection only after busy
	// is cleared (TASK-225 r1). Closing is the fallback if that fails.
	defer func() {
		if conn.SetReadDeadline(time.Now()) != nil {
			_ = conn.Close()
		}
		<-readDone
	}()
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
