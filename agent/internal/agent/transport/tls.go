// Package transport is the agent's only way to reach the manager: HTTPS with
// verified TLS (TS §3.2 Transport, §8.1) and, from TASK-093, the HTTP client.
package transport

import (
	"crypto/sha256"
	"crypto/subtle"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// ErrPinMismatch is returned by the handshake when the manager's leaf key does
// not match manager_spki_sha256.
var ErrPinMismatch = errors.New("transport: the manager's key does not match manager_spki_sha256")

// NewTLSConfig builds the client TLS configuration (#79):
//   - TLS 1.2 at least; Go's defaults prefer TLS 1.3;
//   - the manager certificate and host name are always verified: against the
//     system store when caFile is empty, otherwise against that file's CAs only;
//   - when pinHex is set (64 hex characters, either case), the SHA-256 of the
//     leaf certificate's DER SubjectPublicKeyInfo must also match. The pin is
//     checked in addition to chain and host-name verification, never instead;
//   - no client certificate: agents authenticate with their bsa_ token.
//
// serverName may be empty, in which case net/http uses the URL's host.
func NewTLSConfig(caFile, pinHex, serverName string) (*tls.Config, error) {
	cfg := &tls.Config{
		MinVersion: tls.VersionTLS12,
		ServerName: serverName,
	}
	if caFile != "" {
		pem, err := os.ReadFile(filepath.Clean(caFile))
		if err != nil {
			return nil, fmt.Errorf("transport: read ca_file: %w", err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(pem) {
			return nil, errors.New("transport: ca_file holds no PEM certificate")
		}
		cfg.RootCAs = pool
	}
	if pinHex != "" {
		pin, err := hex.DecodeString(pinHex)
		if err != nil || len(pin) != sha256.Size {
			return nil, errors.New("transport: manager_spki_sha256 must be 64 hex characters")
		}
		// VerifyConnection runs after Go's normal chain and host-name checks,
		// on full and resumed handshakes alike.
		cfg.VerifyConnection = func(cs tls.ConnectionState) error {
			if len(cs.PeerCertificates) == 0 {
				return ErrPinMismatch
			}
			sum := sha256.Sum256(cs.PeerCertificates[0].RawSubjectPublicKeyInfo)
			if subtle.ConstantTimeCompare(sum[:], pin) != 1 {
				return ErrPinMismatch
			}
			return nil
		}
	}
	return cfg, nil
}
