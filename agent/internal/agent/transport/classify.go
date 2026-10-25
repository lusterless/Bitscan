package transport

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"net/http"
	"strconv"
	"time"
)

// MaxRetryAfter caps a Retry-After value, the same ceiling as the 403 and
// Drop waits on rotate (lead ruling 2026-10-25).
const MaxRetryAfter = 24 * time.Hour

// RetryAfter reads a Retry-After header in delta-seconds. A value above
// MaxRetryAfter, including one too large for any integer type, gives
// MaxRetryAfter, so it can never overflow into a short or negative wait.
// Zero, negative, HTTP-date and other unparsable values give 0.
func RetryAfter(v string) time.Duration {
	n, err := strconv.ParseUint(v, 10, 64)
	if err != nil && !errors.Is(err, strconv.ErrRange) {
		return 0
	}
	if n > uint64(MaxRetryAfter/time.Second) { // ErrRange leaves n at the maximum
		return MaxRetryAfter
	}
	return time.Duration(n) * time.Second
}

// Class is what a loop does with an answer (TS §3.3 L224, plan TASK-093).
type Class int

const (
	// Success: 2xx.
	Success Class = iota
	// Drop: the manager will never accept this; log it locally, report it as
	// last_error, do not retry (400, 404, 409, 413, 422, a 403 other than
	// pending_approval, a 3xx (#75), an oversized answer, anything else).
	Drop
	// Stop: any 401; stop every loop until restart (TS §3.2 step 8, #81).
	Stop
	// Wait: 403 pending_approval; keep the request and wait with back-off.
	Wait
	// Retry: 429, 5xx and network or TLS errors; retry with back-off.
	Retry
)

func (c Class) String() string {
	switch c {
	case Success:
		return "success"
	case Drop:
		return "drop"
	case Stop:
		return "stop"
	case Wait:
		return "wait"
	case Retry:
		return "retry"
	}
	return "unknown"
}

// Classify maps a status and problem type, or a transport error, to a Class.
// netErr non-nil means no HTTP answer was received.
func Classify(status int, problemType string, netErr error) Class {
	switch {
	case netErr != nil:
		return Retry
	case status >= 200 && status <= 299:
		return Success
	case status == http.StatusUnauthorized:
		return Stop
	case status == http.StatusForbidden && problemType == "pending_approval":
		return Wait
	case status == http.StatusTooManyRequests, status >= 500 && status <= 599:
		return Retry
	}
	return Drop
}

// IsVerifyError reports whether err is a failed manager certificate, host
// name or pin check, so the caller can log it loudly; it is still retried
// with back-off, because the manager may be fixed, and nothing was sent.
func IsVerifyError(err error) bool {
	var cv *tls.CertificateVerificationError
	var ua x509.UnknownAuthorityError
	var hn x509.HostnameError
	var ci x509.CertificateInvalidError
	return errors.Is(err, ErrPinMismatch) || errors.As(err, &cv) || errors.As(err, &ua) ||
		errors.As(err, &hn) || errors.As(err, &ci)
}
