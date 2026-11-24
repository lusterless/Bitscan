package cmaxclient

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"golang.org/x/sys/unix"
)

const job = "0b7c1d2e-3f40-4a5b-8c6d-7e8f90a1b2c3"

type seen struct {
	line   string
	fds    int
	sealed bool
	kube   string
}

// fakeHelper answers one connection with answer after recording the request.
func fakeHelper(t *testing.T, answer string) (string, <-chan seen) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "collect.sock")
	l, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = l.Close() })
	out := make(chan seen, 1)
	go func() {
		conn, err := l.AcceptUnix()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()
		buf, oob := make([]byte, 4096), make([]byte, 256)
		n, oobn, _, _, err := conn.ReadMsgUnix(buf, oob)
		if err != nil {
			return
		}
		var s seen
		s.line = string(buf[:n])
		if msgs, err := unix.ParseSocketControlMessage(oob[:oobn]); err == nil {
			for _, m := range msgs {
				fds, _ := unix.ParseUnixRights(&m)
				for _, fd := range fds {
					s.fds++
					got, _ := unix.FcntlInt(uintptr(fd), unix.F_GET_SEALS, 0)
					s.sealed = got&seals == seals
					f := os.NewFile(uintptr(fd), "memfd")
					data := make([]byte, 100)
					k, _ := f.ReadAt(data, 0)
					s.kube = string(data[:k])
					_ = f.Close()
				}
			}
		}
		out <- s
		_, _ = conn.Write([]byte(answer))
	}()
	return path, out
}

func TestAuditRoundTripWithAKubeconfig(t *testing.T) {
	head := `{"exit_code":0,"started_at":"2026-11-23T08:00:00Z","finished_at":"2026-11-23T08:20:00Z","cmax_version":"0.3.0",` +
		`"files":[{"name":"report.txt","size":5,"truncated":false},{"name":"run.log","size":3,"truncated":true}]}`
	path, got := fakeHelper(t, head+"\nhellolog")
	c := &Client{Socket: path}
	files := map[string]string{}
	ans, err := c.Audit(context.Background(), Request{JobID: job, Target: "k8s", Vars: map[string]string{"CLUSTERMAX_K8S_GPU_DRA": "1"}},
		[]byte("apiVersion: v1\n"), func(f FileInfo, b []byte) error { files[f.Name] = string(b); return nil })
	if err != nil {
		t.Fatal(err)
	}
	s := <-got
	var req map[string]any
	if json.Unmarshal([]byte(strings.TrimSuffix(s.line, "\n")), &req) != nil || req["target"] != "k8s" || !strings.HasSuffix(s.line, "\n") {
		t.Fatalf("request %q", s.line)
	}
	if s.fds != 1 || !s.sealed || s.kube != "apiVersion: v1\n" {
		t.Fatalf("fd %+v", s)
	}
	if ans.ExitCode != 0 || ans.CmaxVersion != "0.3.0" || files["report.txt"] != "hello" || files["run.log"] != "log" || !ans.Files[1].Truncated {
		t.Fatalf("answer %+v files %v", ans, files)
	}
}

func TestAuditWithoutAKubeconfigSendsNoDescriptor(t *testing.T) {
	path, got := fakeHelper(t, `{"exit_code":3,"started_at":"2026-11-23T08:00:00Z","finished_at":"2026-11-23T08:00:01Z","cmax_version":"0.3.0","files":[]}`+"\n")
	ans, err := (&Client{Socket: path}).Audit(context.Background(), Request{JobID: job, Target: "auto", Vars: map[string]string{}}, nil,
		func(FileInfo, []byte) error { return nil })
	if err != nil || ans.ExitCode != 3 {
		t.Fatalf("ans %+v err %v", ans, err)
	}
	if s := <-got; s.fds != 0 {
		t.Fatalf("fds %d", s.fds)
	}
}

func TestAuditFailures(t *testing.T) {
	for answer, word := range map[string]string{
		"BUSY\n":                         "busy",
		"REFUSED variable not allowed\n": "refused variable not allowed",
		"{\"exit_code\":0}\n":            "protocol",
		`{"exit_code":0,"started_at":"2026-11-23T08:00:00Z","finished_at":"2026-11-23T08:00:01Z","cmax_version":"x","files":[{"name":"report.txt","size":10,"truncated":false}]}` + "\nshort": "broken",
	} {
		path, _ := fakeHelper(t, answer)
		_, err := (&Client{Socket: path}).Audit(context.Background(), Request{JobID: job, Target: "auto", Vars: map[string]string{}}, nil,
			func(FileInfo, []byte) error { return nil })
		var f *Failure
		if !errors.As(err, &f) || f.Word != word {
			t.Errorf("%q: err %v, want %s", answer, err, word)
		}
	}
	_, err := (&Client{Socket: filepath.Join(t.TempDir(), "absent")}).Audit(context.Background(), Request{JobID: job, Target: "auto", Vars: map[string]string{}}, nil,
		func(FileInfo, []byte) error { return nil })
	var f *Failure
	if !errors.As(err, &f) || f.Word != "connect" {
		t.Errorf("absent socket: %v", err)
	}
}
