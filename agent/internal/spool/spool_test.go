// TP-M10-05 (tester-m10): the result spool, REQ-247; #139. Internal test
// (package spool) so the crash hook can be set. Part 1 (persistence) and
// part 2 (API and in-flight state) per the lead's ruling "TASK-212 (spool)
// accepted as built at 489 code lines". Expected values come from REQ-247,
// #139 and plan TASK-212 §2–§3, not from the implementation.
package spool

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/wire"
	"bitscan.local/agent/internal/runner/proto"
)

var t0 = time.Date(2026, 10, 30, 8, 0, 0, 0, time.UTC)

type clock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *clock) now() time.Time      { c.mu.Lock(); defer c.mu.Unlock(); return c.t }
func (c *clock) add(d time.Duration) { c.mu.Lock(); c.t = c.t.Add(d); c.mu.Unlock() }

func jid(n int) wire.UUID { return wire.UUID(fmt.Sprintf("bbbbbbbb-0000-4000-8000-%012d", n)) }
func pid(n int) wire.UUID { return wire.UUID(fmt.Sprintf("00000000-0000-4000-8000-%012d", n)) }

func pids(n int) []wire.UUID {
	out := make([]wire.UUID, n)
	for i := range out {
		out[i] = pid(i + 1)
	}
	return out
}

func res(t testing.TB, plugin wire.UUID, stdout string) proto.Result {
	t.Helper()
	code := int64(0)
	r, err := proto.NewResult(wire.ResultItem{PluginUUID: plugin, ExitCode: &code, Stdout: stdout,
		StartedAt: wire.NewTime(t0), FinishedAt: wire.NewTime(t0.Add(time.Second))})
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func open(t *testing.T, dir string, max int64, c *clock) (*Spool, []Dropped) {
	t.Helper()
	s, d, err := Open(dir, max, c.now)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s, d
}

// diskBytes sums the regular files under dir.
func diskBytes(t *testing.T, dir string) int64 {
	t.Helper()
	var n int64
	err := filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.Type().IsRegular() {
			fi, err := d.Info()
			if err != nil {
				return err
			}
			n += fi.Size()
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return n
}

func checkSize(t *testing.T, s *Spool, dir string) {
	t.Helper()
	if got, disk := s.Size(), diskBytes(t, dir); got != disk {
		t.Fatalf("Size() %d, bytes on disk %d", got, disk)
	}
}

// drain hands out and acks every postable batch, returning them in order.
func drain(t *testing.T, s *Spool, dir string) []Batch {
	t.Helper()
	var out []Batch
	for range 100000 {
		b, ok := s.Next(50, 1_572_864, 30*time.Second)
		if !ok {
			return out
		}
		out = append(out, b)
		if err := s.Ack(b); err != nil {
			t.Fatal(err)
		}
		checkSize(t, s, dir)
	}
	t.Fatal("drain did not end")
	return nil
}

func describe(bs []Batch) string {
	var parts []string
	for _, b := range bs {
		var ids []string
		for _, r := range b.Items {
			ids = append(ids, string(r.Item().PluginUUID)[33:])
		}
		parts = append(parts, fmt.Sprintf("%s:start=%v,final=%v,[%s]", string(b.Job)[33:], b.Start, b.Final, strings.Join(ids, " ")))
	}
	return strings.Join(parts, " | ")
}

// ===== Part 1: persistence =====

// REQ-247 (1), (3): order, size, reopen; a running job becomes interrupted.
func TestP1ReopenOrderAndInterrupted(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	if err := s.StartJob(jid(2), pids(3)); err != nil {
		t.Fatal(err)
	}
	c.add(time.Second)
	if err := s.StartJob(jid(1), pids(2)); err != nil { // later, lower id
		t.Fatal(err)
	}
	for i := 1; i <= 3; i++ {
		if err := s.Put(jid(2), res(t, pid(i), fmt.Sprint("a", i))); err != nil {
			t.Fatal(err)
		}
		checkSize(t, s, dir)
	}
	for i := 1; i <= 2; i++ {
		if err := s.Put(jid(1), res(t, pid(i), fmt.Sprint("b", i))); err != nil {
			t.Fatal(err)
		}
	}
	if err := s.Finish(jid(2)); err != nil {
		t.Fatal(err)
	}
	checkSize(t, s, dir)
	_ = s.Close()
	c.add(time.Hour)
	s2, dropped := open(t, dir, 50<<20, c)
	if len(dropped) != 0 {
		t.Fatalf("dropped %v", dropped)
	}
	checkSize(t, s2, dir)
	if err := s2.Put(jid(1), res(t, pid(1), "late")); !errors.Is(err, ErrJobEnded) {
		t.Fatalf("Put to the interrupted job: %v, want ErrJobEnded", err)
	}
	got := describe(drain(t, s2, dir))
	// job 2 (received first): start, its 3 items in seq order, final; job 1
	// (running at the stop): start, its items, never a final.
	want := "002:start=true,final=false,[] | 002:start=false,final=true,[001 002 003] | " +
		"001:start=true,final=false,[] | 001:start=false,final=false,[001 002]"
	if got != want {
		t.Fatalf("after reopen:\n got %s\nwant %s", got, want)
	}
	if n := diskBytes(t, dir); n != 0 || s2.Size() != 0 {
		t.Fatalf("spool not empty after everything was answered: %d bytes", n)
	}
	ents, _ := os.ReadDir(dir)
	if len(ents) != 0 {
		t.Fatalf("job directories left: %v", ents)
	}
}

// REQ-247 (2), CHK-M10-366: a crash between any two steps of a write leaves
// either no item or a complete one, never a partial file the reader accepts.
func TestP1CrashBetweenSteps(t *testing.T) {
	for _, step := range []string{"created", "written", "synced", "renamed"} {
		t.Run("item/"+step, func(t *testing.T) {
			dir := filepath.Join(t.TempDir(), "spool")
			c := &clock{t: t0}
			s, _ := open(t, dir, 50<<20, c)
			if err := s.StartJob(jid(1), pids(3)); err != nil {
				t.Fatal(err)
			}
			if err := s.Put(jid(1), res(t, pid(1), "one")); err != nil {
				t.Fatal(err)
			}
			s.crash = func(file, st string) error {
				if st == step && strings.HasSuffix(file, "000000000002.json") {
					return errors.New("crash")
				}
				return nil
			}
			if err := s.Put(jid(1), res(t, pid(2), "two")); err == nil {
				t.Fatal("the crash hook did not fire")
			}
			_ = s.Close()
			s2, dropped := open(t, dir, 50<<20, c)
			for _, d := range dropped {
				if d.Reason != "unreadable" {
					t.Fatalf("dropped %v", d)
				}
			}
			checkSize(t, s2, dir)
			_ = filepath.WalkDir(dir, func(p string, d fs.DirEntry, _ error) error {
				if strings.HasSuffix(p, ".tmp") {
					t.Fatalf("a temporary file is left after Open: %s", p)
				}
				return nil
			})
			var items []string
			for _, b := range drain(t, s2, dir) {
				for _, r := range b.Items {
					items = append(items, r.Item().Stdout)
				}
			}
			switch strings.Join(items, ",") {
			case "one":
				if step == "renamed" {
					t.Fatal("after the rename the complete item must survive")
				}
			case "one,two":
				if step != "renamed" {
					t.Fatalf("an item crashed at %q was delivered", step)
				}
			default:
				t.Fatalf("items after the crash at %q: %v", step, items)
			}
		})
		t.Run("manifest/"+step, func(t *testing.T) {
			dir := filepath.Join(t.TempDir(), "spool")
			c := &clock{t: t0}
			s, _ := open(t, dir, 50<<20, c)
			if err := s.StartJob(jid(1), pids(2)); err != nil {
				t.Fatal(err)
			}
			if err := s.Put(jid(1), res(t, pid(1), "one")); err != nil {
				t.Fatal(err)
			}
			s.crash = func(file, st string) error {
				if st == step && strings.HasSuffix(file, "job.json") {
					return errors.New("crash")
				}
				return nil
			}
			_ = s.Finish(jid(1))
			_ = s.Close()
			s2, dropped := open(t, dir, 50<<20, c)
			if len(dropped) != 0 {
				t.Fatalf("dropped %v", dropped)
			}
			checkSize(t, s2, dir)
			bs := drain(t, s2, dir)
			// Before the rename the old manifest stands (running → interrupted:
			// no final); after it the job is finished (final).
			last := bs[len(bs)-1]
			if last.Final != (step == "renamed") || len(last.Items) != 1 {
				t.Fatalf("crash at %q: %s", step, describe(bs))
			}
		})
	}
}

// REQ-247 (2) with planted partial files: a truncated item, an item over the
// stdout cap, a truncated manifest and leftover .tmp files.
func TestP1PlantedPartialFiles(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	for _, j := range []int{1, 2} {
		if err := s.StartJob(jid(j), pids(3)); err != nil {
			t.Fatal(err)
		}
		for i := 1; i <= 2; i++ {
			if err := s.Put(jid(j), res(t, pid(i), "ok")); err != nil {
				t.Fatal(err)
			}
		}
	}
	_ = s.Close()
	j1 := filepath.Join(dir, string(jid(1)))
	full, _ := os.ReadFile(filepath.Join(j1, "000000000002.json")) //nolint:gosec // test path
	write := func(p string, b []byte) {
		if err := os.WriteFile(p, b, 0o600); err != nil { //nolint:gosec // test-owned temp path
			t.Fatal(err)
		}
	}
	write(filepath.Join(j1, "000000000002.json"), full[:len(full)/2])
	big := fmt.Sprintf(`{"plugin_uuid":"%s","exit_code":0,"stdout":"%s","stderr":"","started_at":"2026-10-30T08:00:00Z","finished_at":"2026-10-30T08:00:00Z","timed_out":false,"truncated":false,"error":null}`,
		pid(3), strings.Repeat("x", 65537))
	write(filepath.Join(j1, "000000000003.json"), []byte(big))
	write(filepath.Join(j1, "000000000004.json.tmp"), []byte(`{"plugin_uuid":`))
	write(filepath.Join(j1, "job.json.tmp"), []byte(`{`))
	mf, _ := os.ReadFile(filepath.Join(dir, string(jid(2)), "job.json")) //nolint:gosec // test path
	write(filepath.Join(dir, string(jid(2)), "job.json"), mf[:len(mf)-5])
	s2, dropped := open(t, dir, 50<<20, c)
	got := fmt.Sprint(dropped)
	if !strings.Contains(got, string(jid(1))+" 2 unreadable") || !strings.Contains(got, string(jid(2))+" 0 unreadable") || len(dropped) != 2 {
		t.Fatalf("dropped %v: want job 1 with 2 unreadable items, job 2 unreadable", dropped)
	}
	checkSize(t, s2, dir)
	if _, err := os.Stat(filepath.Join(dir, string(jid(2)))); !errors.Is(err, fs.ErrNotExist) {
		t.Fatal("the job with an unreadable manifest is still on disk")
	}
	bs := drain(t, s2, dir)
	var outs []string
	for _, b := range bs {
		for _, r := range b.Items {
			outs = append(outs, string(r.Item().PluginUUID)[33:])
		}
	}
	if fmt.Sprint(outs) != "[001]" {
		t.Fatalf("delivered %v, want only plugin 1 of job 1", outs)
	}
}

// REQ-247 (4): items of a job received 7 days + 1 s ago are dropped.
func TestP1Expiry(t *testing.T) {
	for _, tc := range []struct {
		age  time.Duration
		keep bool
	}{{7*24*time.Hour - time.Second, true}, {7 * 24 * time.Hour, true}, {7*24*time.Hour + time.Second, false}} {
		t.Run(tc.age.String(), func(t *testing.T) {
			dir := filepath.Join(t.TempDir(), "spool")
			c := &clock{t: t0}
			s, _ := open(t, dir, 50<<20, c)
			if err := s.StartJob(jid(1), pids(2)); err != nil {
				t.Fatal(err)
			}
			_ = s.Put(jid(1), res(t, pid(1), "x"))
			_ = s.Put(jid(1), res(t, pid(2), "y"))
			_ = s.Close()
			c.add(tc.age)
			s2, dropped := open(t, dir, 50<<20, c)
			checkSize(t, s2, dir)
			if tc.keep {
				if len(dropped) != 0 || s2.Size() == 0 {
					t.Fatalf("dropped %v at age %v", dropped, tc.age)
				}
				return
			}
			if len(dropped) != 1 || dropped[0].Reason != "expired" || dropped[0].Items != 2 || dropped[0].Job != jid(1) {
				t.Fatalf("dropped %v, want {%s 2 expired}", dropped, jid(1))
			}
			if s2.Size() != 0 {
				t.Fatal("expired job still counted")
			}
			if _, ok := s2.Next(50, 1_572_864, 0); ok {
				t.Fatal("an expired job's batch was offered")
			}
		})
	}
}

// REQ-247 (5), CHK-M10-356, and "only redacted output can be written": the
// spool's write API takes job ids, plugin uuids and proto.Result only, and a
// file that fails proto.NewResult is never read back (TestP1PlantedPartialFiles).
func TestP1OnlyResultsAndNoCommand(t *testing.T) {
	st := reflect.TypeFor[*Spool]()
	allowed := map[string]bool{"wire.UUID": true, "[]wire.UUID": true, "proto.Result": true, "spool.Batch": true,
		"int": true, "time.Duration": true}
	for i := range st.NumMethod() {
		m := st.Method(i)
		for a := 1; a < m.Type.NumIn(); a++ {
			in := m.Type.In(a).String()
			if !allowed[in] {
				t.Errorf("(*Spool).%s takes %s: a write path for something other than a Result", m.Name, in)
			}
		}
	}
	if f, ok := reflect.TypeFor[Spool]().FieldByName("Log"); !ok || f.Type.String() != "*slog.Logger" {
		t.Error("exported fields changed")
	}
	// The manifest's keys are exactly the #139 (a) set.
	mt := reflect.TypeFor[Manifest]()
	var keys []string
	for i := range mt.NumField() {
		keys = append(keys, strings.Split(mt.Field(i).Tag.Get("json"), ",")[0])
	}
	if got := strings.Join(keys, ","); got != "job_id,received_at,plugins,start_acked,finished,interrupted,final_acked" {
		t.Fatalf("manifest keys %s", got)
	}
	// Canary sweep: an execute or a pattern can't reach the spool at all; the
	// item text is only what the Result carries.
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	if err := s.StartJob(jid(1), pids(1)); err != nil {
		t.Fatal(err)
	}
	if err := s.Put(jid(1), res(t, pid(1), "[REDACTED]")); err != nil {
		t.Fatal(err)
	}
	_ = filepath.WalkDir(dir, func(p string, d fs.DirEntry, _ error) error {
		if d.Type().IsRegular() {
			b, _ := os.ReadFile(p) //nolint:gosec // test path
			if strings.Contains(string(b), "execute") || strings.Contains(string(b), "redaction_patterns") || strings.Contains(string(b), "M10CANARY") {
				t.Fatalf("%s holds a command or pattern key", p)
			}
		}
		return nil
	})
}

// ===== Part 2: the API and in-flight state =====

func TestP2StartJobRules(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	if err := s.StartJob(wire.UUID(strings.ToUpper(string(jid(1)))), []wire.UUID{wire.UUID(strings.ToUpper(string(pid(1))))}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, string(jid(1)))); err != nil {
		t.Fatal("an uppercase job id was not stored lowercase")
	}
	if err := s.Put(jid(1), res(t, pid(1), "x")); err != nil {
		t.Fatalf("lowercase plugin of an uppercase-started job: %v", err)
	}
	for name, err := range map[string]error{
		"duplicate":    s.StartJob(jid(1), pids(1)),
		"0 plugins":    s.StartJob(jid(2), nil),
		"5001 plugins": s.StartJob(jid(3), pids(5001)),
		"bad uuid":     s.StartJob("x", pids(1)),
		"bad plugin":   s.StartJob(jid(4), []wire.UUID{"y"}),
	} {
		if err == nil {
			t.Errorf("%s accepted", name)
		}
	}
	if err := s.StartJob(jid(5), pids(5000)); err != nil {
		t.Errorf("5000 plugins: %v", err)
	}
	checkSize(t, s, dir)
	// ErrFull when the manifest doesn't fit, and nothing written.
	tiny := filepath.Join(t.TempDir(), "spool")
	s2, _ := open(t, tiny, 100, c)
	if err := s2.StartJob(jid(1), pids(3)); !errors.Is(err, ErrFull) {
		t.Fatalf("StartJob into a 100-byte spool: %v, want ErrFull", err)
	}
	if diskBytes(t, tiny) != 0 || s2.Size() != 0 {
		t.Fatal("a refused StartJob left bytes")
	}
	ents, _ := os.ReadDir(tiny)
	if len(ents) != 0 {
		t.Fatalf("a refused StartJob left %v", ents)
	}
}

func TestP2PutRules(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	_ = s.StartJob(jid(1), pids(2))
	if err := s.Put(jid(9), res(t, pid(1), "x")); !errors.Is(err, ErrUnknownJob) {
		t.Errorf("unknown job: %v", err)
	}
	if err := s.Put(jid(1), res(t, pid(3), "x")); !errors.Is(err, ErrUnknownPlugin) {
		t.Errorf("plugin not in the job (CHK-M10-392 defence): %v", err)
	}
	if err := s.Put(jid(1), proto.Result{}); err == nil {
		t.Error("a zero Result was spooled")
	}
	if err := s.Put(jid(1), res(t, wire.UUID(strings.ToUpper(string(pid(2)))), "x")); err != nil {
		t.Errorf("uppercase plugin uuid: %v", err)
	}
	_ = s.Finish(jid(1))
	if err := s.Put(jid(1), res(t, pid(1), "x")); !errors.Is(err, ErrJobEnded) {
		t.Errorf("Put after Finish: %v", err)
	}
	if err := s.Finish(jid(1)); !errors.Is(err, ErrJobEnded) {
		t.Errorf("second Finish: %v", err)
	}
	if err := s.Finish(jid(9)); !errors.Is(err, ErrUnknownJob) {
		t.Errorf("Finish of an unknown job: %v", err)
	}
	checkSize(t, s, dir)
}

// The start notice first; the #141 hold; full batches at once; the size
// bound; at least one item.
func TestP2NextHoldAndBounds(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	_ = s.StartJob(jid(1), pids(60))
	b, ok := s.Next(50, 1_572_864, 30*time.Second)
	if !ok || !b.Start || len(b.Items) != 0 || b.Final {
		t.Fatalf("first batch %+v, want the start notice", b)
	}
	_ = s.Ack(b)
	for i := 1; i <= 3; i++ {
		_ = s.Put(jid(1), res(t, pid(i), "x"))
	}
	c.add(29 * time.Second)
	if _, ok := s.Next(50, 1_572_864, 30*time.Second); ok {
		t.Fatal("a partial batch of a running job went out at 29 s")
	}
	c.add(time.Second)
	b, ok = s.Next(50, 1_572_864, 30*time.Second)
	if !ok || len(b.Items) != 3 || b.Final {
		t.Fatalf("at 30 s: %+v", b)
	}
	_ = s.Ack(b)
	for i := 4; i <= 53; i++ {
		_ = s.Put(jid(1), res(t, pid(i), "x"))
	}
	b, ok = s.Next(50, 1_572_864, 30*time.Second)
	if !ok || len(b.Items) != 50 {
		t.Fatalf("50 ready items: ok %v len %d (a full batch goes at once)", ok, len(b.Items))
	}
	_ = s.Ack(b)
	// The size bound: items of ~40 KiB, a 100,000-byte bound → 2 per batch.
	for i := 54; i <= 58; i++ {
		_ = s.Put(jid(1), res(t, pid(i), strings.Repeat("y", 40000)))
	}
	b, ok = s.Next(50, 100_000, 30*time.Second)
	if !ok || len(b.Items) != 2 {
		t.Fatalf("size bound: ok %v len %d, want 2", ok, len(b.Items))
	}
	body, _ := wire.Encode(wire.ResultsRequest{Results: items(b), Final: false})
	if len(body) > 100_000 {
		t.Fatalf("body %d bytes over the bound", len(body))
	}
	_ = s.Ack(b)
	// One item larger than the bound still goes, alone.
	b, ok = s.Next(50, 10_000, 30*time.Second)
	if !ok || len(b.Items) != 1 {
		t.Fatalf("over-bound single item: ok %v len %d", ok, len(b.Items))
	}
	_ = s.Ack(b)
	checkSize(t, s, dir)
}

func items(b Batch) []wire.ResultItem {
	var out []wire.ResultItem
	for _, r := range b.Items {
		out = append(out, r.Item())
	}
	return out
}

// In flight: one batch per job until answered; an unknown batch can't be
// settled; a dropped start notice still lets the items go (#139 (e)); final
// rules.
func TestP2InFlightAndFinal(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	_ = s.StartJob(jid(1), pids(3))
	c.add(time.Second)
	_ = s.StartJob(jid(2), pids(1))
	b1, _ := s.Next(50, 1_572_864, 0)
	b2, ok := s.Next(50, 1_572_864, 0)
	if !ok || b2.Job != jid(2) || !b2.Start {
		t.Fatalf("with job 1's notice in flight, the next batch is %+v (want job 2's notice)", b2)
	}
	if _, ok := s.Next(50, 1_572_864, 0); ok {
		t.Fatal("a third batch while both jobs are in flight")
	}
	if err := s.Ack(Batch{Job: jid(3)}); err == nil {
		t.Fatal("settled a batch that was never handed out")
	}
	if err := s.Drop(b1); err != nil { // e.g. a 409 on the notice
		t.Fatal(err)
	}
	_ = s.Ack(b2)
	_ = s.Put(jid(1), res(t, pid(1), "x"))
	_ = s.Put(jid(1), res(t, pid(2), "y"))
	b, ok := s.Next(50, 1_572_864, 0)
	if !ok || b.Start || len(b.Items) != 2 || b.Final {
		t.Fatalf("after a dropped notice: %+v", b)
	}
	if err := s.Ack(b); err != nil {
		t.Fatal(err)
	}
	if err := s.Ack(b); err == nil {
		t.Fatal("the same batch settled twice")
	}
	_ = s.Finish(jid(1))
	b, ok = s.Next(50, 1_572_864, 0)
	if !ok || !b.Final || len(b.Items) != 0 {
		t.Fatalf("finished with nothing left: %+v, want an empty final", b)
	}
	_ = s.Ack(b)
	if b, ok := s.Next(50, 1_572_864, 0); ok && b.Job == jid(1) {
		t.Fatalf("a batch after the final: %+v", b)
	}
	if _, err := os.Stat(filepath.Join(dir, string(jid(1)))); !errors.Is(err, fs.ErrNotExist) {
		t.Fatal("job 1's directory is left after its final")
	}
	// The last items batch carries final itself.
	_ = s.Put(jid(2), res(t, pid(1), "z"))
	_ = s.Finish(jid(2))
	b, ok = s.Next(50, 1_572_864, 0)
	if !ok || !b.Final || len(b.Items) != 1 {
		t.Fatalf("last items batch: %+v", b)
	}
	_ = s.Ack(b)
	checkSize(t, s, dir)
	if s.Size() != 0 {
		t.Fatalf("size %d after everything", s.Size())
	}
}

// Races: 8 jobs put concurrently while one sender drains; every item is
// handed out once; size equals the disk at the end.
func TestP2ConcurrentPutAndDrain(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "spool")
	c := &clock{t: t0}
	s, _ := open(t, dir, 50<<20, c)
	const jobs, per = 8, 40
	for j := 1; j <= jobs; j++ {
		if err := s.StartJob(jid(j), pids(per)); err != nil {
			t.Fatal(err)
		}
	}
	start := make(chan struct{})
	var wg sync.WaitGroup
	for j := 1; j <= jobs; j++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			for i := 1; i <= per; i++ {
				if err := s.Put(jid(j), res(t, pid(i), fmt.Sprint(j, "-", i))); err != nil {
					t.Error(err)
				}
			}
			_ = s.Finish(jid(j))
		}()
	}
	seen := map[string]int{}
	finals := 0
	done := make(chan struct{})
	go func() {
		defer close(done)
		<-start
		for finals < jobs {
			b, ok := s.Next(50, 1_572_864, 0)
			if !ok {
				time.Sleep(100 * time.Microsecond)
				continue
			}
			for _, r := range b.Items {
				seen[r.Item().Stdout]++
			}
			if b.Final {
				finals++
			}
			if err := s.Ack(b); err != nil {
				t.Error(err)
				return
			}
		}
	}()
	close(start)
	wg.Wait()
	select {
	case <-done:
	case <-time.After(60 * time.Second):
		t.Fatal("drain did not finish")
	}
	if len(seen) != jobs*per {
		t.Fatalf("%d distinct items, want %d", len(seen), jobs*per)
	}
	for k, n := range seen {
		if n != 1 {
			t.Fatalf("item %s handed out %d times", k, n)
		}
	}
	checkSize(t, s, dir)
}
