package transport

import (
	"bytes"
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"bitscan.local/agent/internal/agent/wire"
)

// Op is one of the six agent routes (TS §6.1, §6.5).
type Op int

const (
	OpEnrol Op = iota
	OpHeartbeat
	OpJobs
	OpResults
	OpInventory
	OpRotate
)

var opNames = [...]string{"enrol", "heartbeat", "jobs", "results", "inventory", "rotate"}

func (o Op) String() string {
	if o < 0 || int(o) >= len(opNames) {
		return "unknown"
	}
	return opNames[o]
}

const (
	// MaxResponse caps a response body: a pull of 10 jobs of 5,000 plugins fits.
	MaxResponse   = 32 << 20
	callTimeout   = 60 * time.Second
	uploadTimeout = 120 * time.Second // inventory
)

// ErrTooLarge is a response body over MaxResponse; its class is Drop.
var ErrTooLarge = errors.New("transport: the manager's answer is larger than the cap")

// Request is one call. Token is the bse_ token for OpEnrol and the bsa_ token
// otherwise; JobID is required for OpResults and optional for OpInventory.
type Request struct {
	Op      Op
	Token   string
	AgentID wire.UUID
	JobID   wire.UUID
	Body    []byte // JSON, or gzip-compressed JSON when Gzip is set
	Gzip    bool
}

// String never shows the token or the body.
func (r Request) String() string { return "transport.Request{" + r.Op.String() + "}" }

// Response is the answer. Problem is set for non-2xx answers (type
// "about:blank" when the body is not a problem). RetryAfter is the
// Retry-After header in seconds, or 0.
type Response struct {
	Status     int
	Body       []byte
	Problem    wire.Problem
	Class      Class
	RetryAfter time.Duration
}

// Client calls the manager. It uses no proxy and follows no redirect (#75).
type Client struct {
	base      *url.URL
	machineID string
	http      *http.Client
}

// NewClient builds the client for managerURL (already checked https:// by
// config) with tlsCfg from NewTLSConfig and the host's /etc/machine-id value.
func NewClient(managerURL string, tlsCfg *tls.Config, machineID wire.MachineID) (*Client, error) {
	base, err := url.Parse(managerURL)
	if err != nil || base.Scheme != "https" || base.Host == "" {
		return nil, errors.New("transport: manager_url must be an https:// URL")
	}
	if err := wire.Validate(machineID); err != nil {
		return nil, errors.New("transport: machine-id must be 32 lowercase hex characters")
	}
	tr := &http.Transport{
		Proxy:               nil, // proxy variables are ignored (#75)
		DialContext:         (&net.Dialer{Timeout: 10 * time.Second}).DialContext,
		TLSClientConfig:     tlsCfg,
		TLSHandshakeTimeout: 10 * time.Second,
		DisableCompression:  true, // no Accept-Encoding; bodies are read as sent
	}
	hc := &http.Client{
		Transport: tr,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse // a 3xx is answered, not followed (#75)
		},
	}
	return &Client{base: base, machineID: string(machineID), http: hc}, nil
}

func (c *Client) target(r Request) (method, u string, err error) {
	if (r.Op != OpEnrol && wire.Validate(r.AgentID) != nil) || (r.JobID != "" && wire.Validate(r.JobID) != nil) {
		return "", "", errors.New("transport: bad agent or job id")
	}
	id, job := strings.ToLower(string(r.AgentID)), strings.ToLower(string(r.JobID))
	q := url.Values{}
	var p []string
	switch r.Op {
	case OpEnrol:
		method, p = http.MethodPost, []string{"enroll"}
	case OpHeartbeat:
		method, p = http.MethodPost, []string{id, "heartbeat"}
	case OpJobs:
		method, p = http.MethodGet, []string{id, "jobs"}
	case OpResults:
		if job == "" {
			return "", "", errors.New("transport: results need a job id")
		}
		method, p = http.MethodPost, []string{id, "jobs", job, "results"}
	case OpInventory:
		method, p = http.MethodPut, []string{id, "inventory"}
		if job != "" {
			q.Set("job_id", job)
		}
	case OpRotate:
		method, p = http.MethodPost, []string{id, "token", "rotate"}
	default:
		return "", "", errors.New("transport: unknown route")
	}
	full := c.base.JoinPath(append([]string{"api", "v1", "agent"}, p...)...)
	full.RawQuery = q.Encode()
	return method, full.String(), nil
}

// Do sends r and reads the answer. A transport failure returns an error and
// a Response with Class Retry; an answer over MaxResponse returns ErrTooLarge
// and Class Drop. Nothing here logs.
func (c *Client) Do(ctx context.Context, r Request) (Response, error) {
	method, u, err := c.target(r)
	if err != nil {
		return Response{Class: Drop}, err
	}
	timeout := callTimeout
	if r.Op == OpInventory {
		timeout = uploadTimeout
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	var body io.Reader
	if r.Body != nil {
		body = bytes.NewReader(r.Body)
	}
	req, err := http.NewRequestWithContext(ctx, method, u, body)
	if err != nil {
		return Response{Class: Drop}, fmt.Errorf("transport: build the %s request: %w", r.Op, err)
	}
	req.Header.Set("Authorization", "Bearer "+r.Token)
	if r.Op != OpEnrol {
		req.Header.Set("X-Bitscan-Machine-Id", c.machineID)
	}
	if r.Body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if r.Gzip {
		req.Header.Set("Content-Encoding", "gzip")
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return Response{Class: Retry}, fmt.Errorf("transport: %s call: %w", r.Op, err)
	}
	defer func() { _ = resp.Body.Close() }()
	out := Response{Status: resp.StatusCode}
	if resp.ContentLength > MaxResponse {
		out.Class = Drop
		return out, ErrTooLarge
	}
	out.Body, err = io.ReadAll(io.LimitReader(resp.Body, MaxResponse+1))
	if err != nil {
		out.Class = Retry
		return out, fmt.Errorf("transport: read the %s answer: %w", r.Op, err)
	}
	if len(out.Body) > MaxResponse {
		out.Body, out.Class = nil, Drop
		return out, ErrTooLarge
	}
	if out.Status < 200 || out.Status > 299 {
		out.Problem, _ = wire.DecodeProblem(out.Body) // not a problem body: type stays empty
		if out.Problem.Type == "" {
			out.Problem.Type = "about:blank"
		}
	}
	out.RetryAfter = RetryAfter(resp.Header.Get("Retry-After"))
	out.Class = Classify(out.Status, out.Problem.Type, nil)
	return out, nil
}
