// Package state keeps the agent's files in /var/lib/bitscan-agent (TS §3.1,
// §3.2 steps 3–4): agent_id (0644), token (0600), token.json (0600, the
// token's issued_at and expires_at), enroll.token (read, then deleted) and
// seen_jobs.json (0600). Every write is atomic: temporary file, fsync, rename,
// fsync of the directory. All access goes through os.Root, so no path or
// symlink can lead outside the directory.
package state

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"strings"
	"sync"
	"time"

	"bitscan.local/agent/internal/agent/wire"
)

const (
	fileAgentID    = "agent_id"
	fileToken      = "token"
	fileTokenTimes = "token.json"
	fileEnrolToken = "enroll.token"
)

// Store is the open state directory. It is safe for concurrent use.
type Store struct {
	root *os.Root
	mu   sync.Mutex // one file write at a time, so temporary names never collide
	tok  sync.Mutex // token and token.json are written as a pair
	// crash, when set (tests only), is called after each write step; an error
	// stops the write there, leaving the files as a crash at that point would.
	crash func(file, step string) error
}

// Token is the agent token with its lifetime. TimesKnown is false when
// token.json is missing or belongs to another token (a crash between the two
// writes); the rotation logic then treats the window as open (TASK-099 plan).
type Token struct {
	Value      wire.AgentToken
	IssuedAt   time.Time
	ExpiresAt  time.Time
	TimesKnown bool
}

type tokenTimes struct {
	IssuedAt    time.Time `json:"issued_at"`
	ExpiresAt   time.Time `json:"expires_at"`
	TokenSHA256 string    `json:"token_sha256"` // binds the times to their token
}

// Open opens dir (config.StateDir in production), which must already exist.
func Open(dir string) (*Store, error) {
	root, err := os.OpenRoot(dir)
	if err != nil {
		return nil, fmt.Errorf("state: open the state directory: %w", err)
	}
	return &Store{root: root}, nil
}

func (s *Store) Close() error { return s.root.Close() }

// AgentID returns the stored id; a missing file gives an error matching
// fs.ErrNotExist.
func (s *Store) AgentID() (wire.UUID, error) {
	b, err := s.root.ReadFile(fileAgentID)
	if err != nil {
		return "", fmt.Errorf("state: read agent_id: %w", err)
	}
	id := wire.UUID(strings.ToLower(strings.TrimSpace(string(b))))
	if err := wire.Validate(id); err != nil {
		return "", errors.New("state: agent_id: not a UUID")
	}
	return id, nil
}

// Token returns the stored token; a missing token file gives an error
// matching fs.ErrNotExist.
func (s *Store) Token() (Token, error) {
	b, err := s.root.ReadFile(fileToken)
	if err != nil {
		return Token{}, fmt.Errorf("state: read token: %w", err)
	}
	t := Token{Value: wire.AgentToken(strings.TrimSpace(string(b)))}
	if err := wire.Validate(t.Value); err != nil {
		return Token{}, errors.New("state: token: not a bsa_ token")
	}
	b, err = s.root.ReadFile(fileTokenTimes)
	if errors.Is(err, fs.ErrNotExist) {
		return t, nil
	}
	if err != nil {
		return Token{}, fmt.Errorf("state: read token.json: %w", err)
	}
	var tt tokenTimes
	if err := json.Unmarshal(b, &tt); err != nil {
		return Token{}, errors.New("state: token.json: unreadable")
	}
	if tt.TokenSHA256 == tokenHash(t.Value) {
		t.IssuedAt, t.ExpiresAt, t.TimesKnown = tt.IssuedAt, tt.ExpiresAt, true
	}
	return t, nil
}

// EnrolToken returns the bse_ token from enroll.token; a missing file gives
// an error matching fs.ErrNotExist.
func (s *Store) EnrolToken() (string, error) {
	b, err := s.root.ReadFile(fileEnrolToken)
	if err != nil {
		return "", fmt.Errorf("state: read enroll.token: %w", err)
	}
	tok := strings.TrimSpace(string(b))
	if tok == "" {
		return "", errors.New("state: enroll.token: empty")
	}
	return tok, nil
}

// SaveEnrolment writes agent_id, token and token.json, in that order.
func (s *Store) SaveEnrolment(id wire.UUID, t Token) error {
	if err := wire.Validate(id); err != nil {
		return errors.New("state: agent_id: not a UUID")
	}
	if err := s.writeFile(fileAgentID, []byte(strings.ToLower(string(id))+"\n"), 0o644); err != nil {
		return err
	}
	return s.SaveToken(t)
}

// SaveToken writes token, then token.json (after enrolment or a rotation).
func (s *Store) SaveToken(t Token) error {
	if err := wire.Validate(t.Value); err != nil {
		return errors.New("state: token: not a bsa_ token")
	}
	s.tok.Lock()
	defer s.tok.Unlock()
	times, err := json.Marshal(tokenTimes{IssuedAt: t.IssuedAt.UTC(), ExpiresAt: t.ExpiresAt.UTC(), TokenSHA256: tokenHash(t.Value)})
	if err != nil {
		return fmt.Errorf("state: encode token.json: %w", err)
	}
	if err := s.writeFile(fileToken, []byte(string(t.Value)+"\n"), 0o600); err != nil {
		return err
	}
	return s.writeFile(fileTokenTimes, times, 0o600)
}

// DeleteEnrolToken removes enroll.token; a missing file is not an error.
func (s *Store) DeleteEnrolToken() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.root.Remove(fileEnrolToken); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return fmt.Errorf("state: delete enroll.token: %w", err)
	}
	return s.syncDir()
}

func tokenHash(t wire.AgentToken) string {
	sum := sha256.Sum256([]byte(t))
	return hex.EncodeToString(sum[:])
}

func (s *Store) step(file, step string) error {
	if s.crash == nil {
		return nil
	}
	return s.crash(file, step)
}

// writeFile replaces name atomically with data at exactly mode.
func (s *Store) writeFile(name string, data []byte, mode os.FileMode) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	tmp := "." + name + ".tmp"
	if err := s.root.Remove(tmp); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return fmt.Errorf("state: remove a stale %s: %w", tmp, err)
	}
	f, err := s.root.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		return fmt.Errorf("state: create %s: %w", tmp, err)
	}
	werr := func() error {
		if err := f.Chmod(mode); err != nil { // exact mode whatever the umask
			return fmt.Errorf("state: chmod %s: %w", tmp, err)
		}
		if err := s.step(name, "created"); err != nil {
			return err
		}
		if _, err := f.Write(data); err != nil {
			return fmt.Errorf("state: write %s: %w", tmp, err)
		}
		if err := s.step(name, "written"); err != nil {
			return err
		}
		if err := f.Sync(); err != nil {
			return fmt.Errorf("state: fsync %s: %w", tmp, err)
		}
		return s.step(name, "synced")
	}()
	cerr := f.Close()
	if werr != nil {
		return werr
	}
	if cerr != nil {
		return fmt.Errorf("state: close %s: %w", tmp, cerr)
	}
	if err := s.root.Rename(tmp, name); err != nil {
		return fmt.Errorf("state: rename %s: %w", tmp, err)
	}
	if err := s.step(name, "renamed"); err != nil {
		return err
	}
	return s.syncDir()
}

func (s *Store) syncDir() error {
	d, err := s.root.Open(".")
	if err != nil {
		return fmt.Errorf("state: open the state directory: %w", err)
	}
	defer func() { _ = d.Close() }()
	if err := d.Sync(); err != nil {
		return fmt.Errorf("state: fsync the state directory: %w", err)
	}
	return nil
}
