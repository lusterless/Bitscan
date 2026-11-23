// Package cmaxclient asks cmax-helper, the ClusterMAX scanner role, to run
// the one fixed audit of a cluster_audit job (TS §3.8; owner decision
// 2026-11-23). It is the agent's only helper call: one JSON request with at
// most one sealed memfd holding the job's kubeconfig, then the answer header
// and the files. The kubeconfig never touches a file system, and nothing
// here logs.
package cmaxclient

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"strings"
	"time"

	"golang.org/x/sys/unix"

	"bitscan.local/agent/internal/agent/wire"
)

// Socket is the helper's socket, created by cmax-helper.socket (TS §3.8).
const Socket = "/run/clustermax/collect.sock"

const (
	// AuditLimit is the helper's 4 h limit plus slack for the answer.
	AuditLimit = 4*time.Hour + 10*time.Minute
	// MaxFile is the helper's cap per file (TS §3.8).
	MaxFile   = 64 << 20
	maxHeader = 64 << 10
	seals     = unix.F_SEAL_SEAL | unix.F_SEAL_SHRINK | unix.F_SEAL_GROW | unix.F_SEAL_WRITE
)

// Failure means the helper did not run the audit. Word is connect,
// refused <reason>, busy, broken or protocol.
type Failure struct{ Word string }

func (f *Failure) Error() string { return "cmaxclient: " + f.Word }

// Request is the audit request (TS §3.8).
type Request struct {
	JobID  wire.UUID         `json:"job_id"`
	Target string            `json:"target"`
	Vars   map[string]string `json:"vars"`
}

// FileInfo is one file of the answer, in order.
type FileInfo struct {
	Name      string `json:"name"`
	Size      int64  `json:"size"`
	Truncated bool   `json:"truncated"`
}

// Answer is the helper's header line.
type Answer struct {
	ExitCode    int64      `json:"exit_code"`
	StartedAt   wire.Time  `json:"started_at"`
	FinishedAt  wire.Time  `json:"finished_at"`
	CmaxVersion string     `json:"cmax_version"`
	Files       []FileInfo `json:"files"`
}

// Client talks to the helper. A zero Socket is Socket.
type Client struct{ Socket string }

// Audit sends req, with kubeconfig in a sealed memfd when it is not nil, and
// calls onFile for each file of the answer with exactly its bytes. It
// returns a *Failure when the helper did not answer with a run, ctx.Err()
// when the agent stops, or onFile's error.
func (c *Client) Audit(ctx context.Context, req Request, kubeconfig []byte, onFile func(FileInfo, []byte) error) (Answer, error) {
	path := c.Socket
	if path == "" {
		path = Socket
	}
	line, err := json.Marshal(req)
	if err != nil || len(line) >= 4096 {
		return Answer{}, &Failure{Word: "protocol"}
	}
	var d net.Dialer
	nc, err := d.DialContext(ctx, "unix", path)
	if err != nil {
		if ctx.Err() != nil {
			return Answer{}, ctx.Err()
		}
		return Answer{}, &Failure{Word: "connect"}
	}
	conn, _ := nc.(*net.UnixConn)
	defer func() { _ = conn.Close() }()
	stop := context.AfterFunc(ctx, func() { _ = conn.Close() })
	defer stop()
	_ = conn.SetDeadline(time.Now().Add(AuditLimit))
	if err := send(conn, append(line, '\n'), kubeconfig); err != nil {
		return Answer{}, c.broken(ctx, err)
	}
	br := bufio.NewReaderSize(conn, maxHeader)
	head, err := br.ReadSlice('\n')
	if err != nil {
		return Answer{}, c.broken(ctx, err)
	}
	text := strings.TrimSpace(string(head))
	switch {
	case text == "BUSY":
		return Answer{}, &Failure{Word: "busy"}
	case strings.HasPrefix(text, "REFUSED "):
		return Answer{}, &Failure{Word: "refused " + printable(strings.TrimPrefix(text, "REFUSED "))}
	}
	var ans Answer
	if wire.DecodeStrict(head, &ans) != nil || len(ans.Files) > 4 {
		return Answer{}, &Failure{Word: "protocol"}
	}
	for _, f := range ans.Files {
		if f.Size < 0 || f.Size > MaxFile {
			return Answer{}, &Failure{Word: "protocol"}
		}
		buf := make([]byte, f.Size)
		if _, err := io.ReadFull(br, buf); err != nil {
			return Answer{}, c.broken(ctx, err)
		}
		if err := onFile(f, buf); err != nil {
			return Answer{}, fmt.Errorf("cmaxclient: %w", err)
		}
	}
	return ans, nil
}

// broken is a failed read or write: ctx.Err() when the agent stops, else a
// fixed word (the error text is never shown).
func (c *Client) broken(ctx context.Context, _ error) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	return &Failure{Word: "broken"}
}

// send writes the request line; with a kubeconfig, its sealed memfd rides
// along (SCM_RIGHTS) and the agent's copy is closed right after.
func send(conn *net.UnixConn, line, kubeconfig []byte) error {
	if kubeconfig == nil {
		_, err := conn.Write(line)
		return err
	}
	fd, err := sealedMemfd(kubeconfig)
	if err != nil {
		return err
	}
	defer func() { _ = unix.Close(fd) }()
	n, _, err := conn.WriteMsgUnix(line, unix.UnixRights(fd), nil)
	if err == nil && n != len(line) {
		err = io.ErrShortWrite
	}
	return err
}

// sealedMemfd is an anonymous memory file holding data, sealed so neither
// side can change it (TS §3.8).
func sealedMemfd(data []byte) (int, error) {
	fd, err := unix.MemfdCreate("kubeconfig", unix.MFD_CLOEXEC|unix.MFD_ALLOW_SEALING)
	if err != nil {
		return -1, fmt.Errorf("memfd: %w", err)
	}
	for off := 0; off < len(data); {
		n, err := unix.Write(fd, data[off:])
		if err != nil {
			_ = unix.Close(fd)
			return -1, fmt.Errorf("memfd: %w", err)
		}
		off += n
	}
	if _, err := unix.FcntlInt(uintptr(fd), unix.F_ADD_SEALS, seals); err != nil {
		_ = unix.Close(fd)
		return -1, fmt.Errorf("memfd: %w", err)
	}
	return fd, nil
}

// Harden makes the agent process non-dumpable (no core file, no ptrace by
// other users), so a kubeconfig in its memory is not written out (TS §3.8).
func Harden() error {
	if err := unix.Prctl(unix.PR_SET_DUMPABLE, 0, 0, 0, 0); err != nil {
		return fmt.Errorf("cmaxclient: prctl: %w", err)
	}
	return nil
}

// printable keeps a refusal reason short and plain.
func printable(s string) string {
	var b strings.Builder
	for _, r := range s {
		if b.Len() >= 64 {
			break
		}
		if r >= 0x20 && r < 0x7f {
			b.WriteRune(r)
		}
	}
	return b.String()
}
