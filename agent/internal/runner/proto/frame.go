package proto

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"

	"bitscan.local/agent/internal/agent/wire"
)

// A frame is a 4-byte big-endian length, then that many bytes holding one
// compact JSON object (#130 (b)).

// The reply shapes on the wire; each is decoded strictly, so each refuses
// keys of the others.
type (
	typeOnly struct {
		Type Kind `json:"type"`
	}
	refusedMsg struct {
		Type   Kind   `json:"type"`
		Reason Reason `json:"reason"`
	}
	resultMsg struct {
		Type   Kind            `json:"type"`
		Result wire.ResultItem `json:"result"`
	}
)

var errReply = errors.New("proto: reply not sendable")

func writeFrame(w io.Writer, body []byte, limit uint32) error {
	n := len(body)
	if n <= 0 || n > math.MaxUint32 || uint32(n) > limit {
		return ErrFrame
	}
	buf := make([]byte, 4, 4+n)
	binary.BigEndian.PutUint32(buf, uint32(n))
	buf = append(buf, body...)
	if _, err := w.Write(buf); err != nil {
		return fmt.Errorf("proto: write frame: %w", err)
	}
	return nil
}

// readFrame refuses a zero or oversize length after reading only the 4-byte
// header. A clean end before the header is returned wrapping io.EOF; a header
// or body cut short is ErrFrame wrapping io.ErrUnexpectedEOF; other read
// errors (deadlines included) are wrapped as they are.
func readFrame(r io.Reader, limit uint32) ([]byte, error) {
	var hdr [4]byte
	if _, err := io.ReadFull(r, hdr[:]); err != nil {
		if errors.Is(err, io.ErrUnexpectedEOF) {
			return nil, fmt.Errorf("%w: %w", ErrFrame, err)
		}
		return nil, fmt.Errorf("proto: read frame: %w", err)
	}
	n := binary.BigEndian.Uint32(hdr[:])
	if n == 0 || n > limit {
		return nil, ErrFrame
	}
	body := make([]byte, n)
	if _, err := io.ReadFull(r, body); err != nil {
		if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
			return nil, fmt.Errorf("%w: %w", ErrFrame, io.ErrUnexpectedEOF)
		}
		return nil, fmt.Errorf("proto: read frame: %w", err)
	}
	return body, nil
}

// checkRequest holds the rules beyond the wire contract (#130 (c)). Rules
// that need the clock or files are the runner's job checks (#132).
func checkRequest(req Request) error {
	switch {
	case req.V != Version:
		return ErrMalformed
	case req.Job.Kind != wire.KindCompliance:
		return fmt.Errorf("%w: %w", ErrMalformed, ErrNotCompliance)
	case req.MaxParallelPlugins < minParallel || req.MaxParallelPlugins > maxParallel:
		return ErrMalformed
	}
	return nil
}

// WriteRequest sends req as one frame. It refuses, writing nothing, a request
// the runner would refuse at decode.
func WriteRequest(w io.Writer, req Request) error {
	if err := checkRequest(req); err != nil {
		return err
	}
	body, err := wire.Encode(req)
	if err != nil {
		return fmt.Errorf("%w: request not sendable", ErrMalformed)
	}
	return writeFrame(w, body, MaxRequest)
}

// ReadRequest reads exactly one frame and decodes it strictly: unknown or
// missing keys at any level, wrong types, trailing data and the #60 bounds
// are refused. It never reads past the frame.
func ReadRequest(r io.Reader) (Request, error) {
	body, err := readFrame(r, MaxRequest)
	if err != nil {
		return Request{}, err
	}
	var req Request
	if wire.DecodeStrict(body, &req) != nil {
		return Request{}, ErrMalformed
	}
	if err := checkRequest(req); err != nil {
		return Request{}, err
	}
	return req, nil
}

// WriteReply sends rep as one frame. A result is checked again before it is
// sent (#130 (i)).
func WriteReply(w io.Writer, rep Reply) error {
	var msg any
	switch rep.Kind {
	case KindAccepted, KindDone:
		msg = typeOnly{Type: rep.Kind}
	case KindRefused:
		if !rep.Reason.valid() {
			return errReply
		}
		msg = refusedMsg{Type: rep.Kind, Reason: rep.Reason}
	case KindResult:
		if checkItem(rep.Result.item) != nil {
			return errReply
		}
		msg = resultMsg{Type: rep.Kind, Result: rep.Result.item}
	default:
		return errReply
	}
	body, err := wire.Encode(msg)
	if err != nil {
		return errReply
	}
	return writeFrame(w, body, MaxReply)
}

// ReadReply reads exactly one frame: first the type, then the strict shape
// for that type. A result must also pass NewResult.
func ReadReply(r io.Reader) (Reply, error) {
	body, err := readFrame(r, MaxReply)
	if err != nil {
		return Reply{}, err
	}
	var probe typeOnly
	if json.Unmarshal(body, &probe) != nil {
		return Reply{}, ErrMalformed
	}
	switch probe.Type {
	case KindAccepted, KindDone:
		var m typeOnly
		if wire.DecodeStrict(body, &m) != nil {
			return Reply{}, ErrMalformed
		}
		return Reply{Kind: m.Type}, nil
	case KindRefused:
		var m refusedMsg
		if wire.DecodeStrict(body, &m) != nil || !m.Reason.valid() {
			return Reply{}, ErrMalformed
		}
		return Reply{Kind: m.Type, Reason: m.Reason}, nil
	case KindResult:
		var m resultMsg
		if wire.DecodeStrict(body, &m) != nil {
			return Reply{}, ErrMalformed
		}
		res, err := NewResult(m.Result)
		if err != nil {
			return Reply{}, ErrMalformed
		}
		return Reply{Kind: m.Type, Result: res}, nil
	}
	return Reply{}, ErrMalformed
}
