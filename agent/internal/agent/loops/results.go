package loops

import (
	"bytes"
	"compress/gzip"
	"fmt"
	"time"

	"bitscan.local/agent/internal/agent/schedule"
	"bitscan.local/agent/internal/agent/transport"
	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/spool"
)

const (
	// maxBatchBody is 1.5 MB of uncompressed JSON (TS §3.5 L253; #57, #141):
	// the manager's cap applies after decompression.
	maxBatchBody = 1_572_864
	// holdYoung: a running job's partial batch waits until its oldest item
	// is this old (#141).
	holdYoung = 30 * time.Second
)

// Sender is the one results sender (#141): it posts each job's spooled
// entries in order, the start notice first and the final batch last
// (TS §3.3 L222, §3.5 L253). One goroutine runs Loop, so a job's batches are
// never posted out of order or in parallel (REQ-246 (6)).
type Sender struct {
	Run   *Run
	Spool *spool.Spool
	wake  chan struct{}
}

func NewSender(r *Run, s *spool.Spool) *Sender {
	return &Sender{Run: r, Spool: s, wake: make(chan struct{}, 1)}
}

// Wake tells the sender the spool changed (a job started, a result was
// spooled, a job finished). It never blocks.
func (s *Sender) Wake() {
	select {
	case s.wake <- struct{}{}:
	default:
	}
}

// Loop posts until the Run stops. With nothing postable it waits for Wake.
// The first wake after a post arms one holdYoung timer: every item spooled
// since then is younger than the timer, so when it fires the oldest held
// item is at least holdYoung old and goes out (#141).
//
// A failed attempt (Wait or Retry) releases the batch before the back-off,
// so overflow may convert its items meanwhile, and the retry is a fresh
// batch from Next, never the old body (#140 reading, decisions 2026-10-30).
func (s *Sender) Loop() {
	r := s.Run
	var hold <-chan time.Time
	back := schedule.NewBackoff(r.Rand())
	for {
		if b, ok := s.Spool.Next(maxBatch, maxBatchBody, holdYoung); ok {
			switch s.post(b) {
			case transport.Stop:
				return
			case transport.Wait, transport.Retry:
				if s.Spool.Release(b) != nil {
					r.Log().Error("the spool could not take back an unsent batch", "job_id", string(b.Job))
				}
				if schedule.Sleep(r.Context(), r.Clock(), back.Next()) != nil {
					return
				}
			default:
				back.Reset()
				hold = nil
			}
			continue
		}
		select {
		case <-r.Context().Done():
			return
		case <-s.wake:
			if hold == nil {
				hold = r.Clock().After(holdYoung)
			}
		case <-hold:
			hold = nil
			if s.Spool.Size() > 0 { // a job is still open: check again later
				hold = r.Clock().After(holdYoung)
			}
		}
	}
}

// post makes one gzip-compressed attempt for b and returns its class.
// Success settles it with Ack, a Drop answer with Drop (Run.Call has logged
// it and set last_error, TS §3.3 L224). Wait and Retry leave it in flight
// for the caller to release and back off (10 s → 5 min); Stop means the Run
// stopped (a 401; also when SIGTERM cut the attempt).
func (s *Sender) post(b spool.Batch) transport.Class {
	r := s.Run
	items := make([]wire.ResultItem, 0, len(b.Items))
	for _, it := range b.Items {
		items = append(items, it.Item())
	}
	body, err := gzipBody(wire.ResultsRequest{Results: items, Final: b.Final})
	if err != nil {
		r.Log().Error("the results batch failed the contract check; dropped", "job_id", string(b.Job))
		r.SetLastError("results batch refused")
		s.settle(b, s.Spool.Drop)
		return transport.Drop
	}
	resp, _ := r.Call(r.Context(), transport.Request{Op: transport.OpResults, JobID: b.Job, Body: body, Gzip: true})
	switch resp.Class {
	case transport.Success:
		var rr wire.ResultsResponse
		if wire.DecodeStrict(resp.Body, &rr) != nil {
			r.Log().Warn("the results answer failed the contract check; the batch counts as sent", "job_id", string(b.Job))
		}
		s.settle(b, s.Spool.Ack)
	case transport.Drop:
		s.settle(b, s.Spool.Drop)
	case transport.Wait, transport.Retry:
		if r.Context().Err() != nil {
			return transport.Stop
		}
	}
	return resp.Class
}

func (s *Sender) settle(b spool.Batch, f func(spool.Batch) error) {
	if f(b) != nil {
		s.Run.Log().Error("the spool could not record a posted batch; it may be posted again", "job_id", string(b.Job))
	}
}

func gzipBody(req wire.ResultsRequest) ([]byte, error) {
	raw, err := wire.Encode(req)
	if err != nil {
		return nil, fmt.Errorf("loops: results batch: %w", err)
	}
	var buf bytes.Buffer
	zw := gzip.NewWriter(&buf)
	if _, err := zw.Write(raw); err != nil {
		return nil, fmt.Errorf("loops: gzip: %w", err)
	}
	if err := zw.Close(); err != nil {
		return nil, fmt.Errorf("loops: gzip: %w", err)
	}
	return buf.Bytes(), nil
}
