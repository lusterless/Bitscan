// Tests for the agent's TLS configuration (TS §3.2 Transport L194, §2.2,
// §8.1, §8.3 Security L1283; #79; REQ-094; tests/m4/test-plan.md TP-M4-04,
// CHK-M4-040 to -046; mutation rows CHK-M4-321 to -326). The test PKI is made
// here: root CA A (trusted through ca_file), root CA B (untrusted), an
// intermediate I under A, and leaves. Expected values come from the spec and
// #79, not from the implementation.
package transport_test

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/pem"
	"errors"
	"io"
	"log"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"bitscan.local/agent/internal/agent/transport"
)

type ca struct {
	cert *x509.Certificate
	key  *ecdsa.PrivateKey
	der  []byte
}

type leaf struct {
	tls  tls.Certificate
	cert *x509.Certificate
}

var serial atomic.Int64

func newKey(t testing.TB) *ecdsa.PrivateKey {
	t.Helper()
	k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return k
}

func newCA(t testing.TB, name string, parent *ca) *ca {
	t.Helper()
	c, err := makeCA(name, parent)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func makeCA(name string, parent *ca) (*ca, error) {
	k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(serial.Add(1)),
		Subject:               pkix.Name{CommonName: name},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(24 * time.Hour),
		IsCA:                  true,
		BasicConstraintsValid: true,
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature,
	}
	signer, signKey := tmpl, k
	if parent != nil {
		signer, signKey = parent.cert, parent.key
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, signer, &k.PublicKey, signKey)
	if err != nil {
		return nil, err
	}
	c, err := x509.ParseCertificate(der)
	if err != nil {
		return nil, err
	}
	return &ca{cert: c, key: k, der: der}, nil
}

type leafOpt struct {
	dns       []string
	ips       []net.IP
	notBefore time.Time
	notAfter  time.Time
	chain     []*ca // intermediates sent by the server, leaf issuer first
}

func newLeaf(t testing.TB, issuer *ca, o leafOpt) leaf {
	t.Helper()
	k := newKey(t)
	if o.notBefore.IsZero() {
		o.notBefore = time.Now().Add(-time.Hour)
	}
	if o.notAfter.IsZero() {
		o.notAfter = time.Now().Add(24 * time.Hour)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(serial.Add(1)),
		Subject:      pkix.Name{CommonName: "bitscan manager"},
		NotBefore:    o.notBefore,
		NotAfter:     o.notAfter,
		DNSNames:     o.dns,
		IPAddresses:  o.ips,
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, issuer.cert, &k.PublicKey, issuer.key)
	if err != nil {
		t.Fatal(err)
	}
	c, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	chain := [][]byte{der}
	for _, i := range o.chain {
		chain = append(chain, i.der)
	}
	return leaf{tls: tls.Certificate{Certificate: chain, PrivateKey: k, Leaf: c}, cert: c}
}

func local() leafOpt {
	return leafOpt{dns: []string{"localhost"}, ips: []net.IP{net.ParseIP("127.0.0.1")}}
}

func pinOf(c *x509.Certificate) string {
	sum := sha256.Sum256(c.RawSubjectPublicKeyInfo)
	return hex.EncodeToString(sum[:])
}

func writePEM(t testing.TB, dir, name string, cas ...*ca) string {
	t.Helper()
	var b bytes.Buffer
	for _, c := range cas {
		if err := pem.Encode(&b, &pem.Block{Type: "CERTIFICATE", Bytes: c.der}); err != nil {
			t.Fatal(err)
		}
	}
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, b.Bytes(), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

// server is a recording TLS server: the handler counts calls and body bytes,
// so "refused before any request body is sent" is checked as zero of both.
type server struct {
	*httptest.Server
	calls, bodyBytes atomic.Int64
	clientCerts      atomic.Int64
}

func newServer(t testing.TB, l leaf, minV, maxV uint16, clientAuth tls.ClientAuthType) *server {
	t.Helper()
	s := &server{}
	s.Server = httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		s.calls.Add(1)
		n, _ := io.Copy(io.Discard, r.Body)
		s.bodyBytes.Add(n)
		if r.TLS != nil {
			s.clientCerts.Add(int64(len(r.TLS.PeerCertificates)))
		}
		_, _ = w.Write([]byte("ok"))
	}))
	s.TLS = &tls.Config{Certificates: []tls.Certificate{l.tls}, MinVersion: minV, MaxVersion: maxV, ClientAuth: clientAuth}
	s.Config.ErrorLog = log.New(io.Discard, "", 0)
	s.StartTLS()
	t.Cleanup(s.Close)
	return s
}

// post sends one request with a body through a transport built on cfg.
func post(cfg *tls.Config, url string) (*http.Response, error) {
	tr := &http.Transport{TLSClientConfig: cfg, Proxy: nil, DisableKeepAlives: true}
	defer tr.CloseIdleConnections()
	c := &http.Client{Transport: tr, Timeout: 10 * time.Second}
	resp, err := c.Post(url, "application/json", strings.NewReader(`{"canary":"BODY-CANARY"}`))
	if err != nil {
		return nil, err
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	_ = resp.Body.Close()
	return resp, nil
}

type pki struct {
	dir                      string
	a, b, inter              *ca
	aFile, bFile             string
	good, wrongHost, expired leaf
	notYet, viaInter, fromB  leaf
}

func newPKI(t testing.TB) *pki {
	t.Helper()
	p := &pki{dir: t.TempDir()}
	p.a = newCA(t, "CA A", nil)
	p.b = newCA(t, "CA B", nil)
	p.inter = newCA(t, "intermediate I", p.a)
	p.aFile = writePEM(t, p.dir, "a.pem", p.a)
	p.bFile = writePEM(t, p.dir, "b.pem", p.b)
	p.good = newLeaf(t, p.a, local())
	p.wrongHost = newLeaf(t, p.a, leafOpt{dns: []string{"wrong.example"}})
	o := local()
	o.notBefore, o.notAfter = time.Now().Add(-48*time.Hour), time.Now().Add(-24*time.Hour)
	p.expired = newLeaf(t, p.a, o)
	o = local()
	o.notBefore, o.notAfter = time.Now().Add(24*time.Hour), time.Now().Add(48*time.Hour)
	p.notYet = newLeaf(t, p.a, o)
	o = local()
	o.chain = []*ca{p.inter}
	p.viaInter = newLeaf(t, p.inter, o)
	p.fromB = newLeaf(t, p.b, local())
	return p
}

func mustConfig(t *testing.T, caFile, pin string) *tls.Config {
	t.Helper()
	cfg, err := transport.NewTLSConfig(caFile, pin, "")
	if err != nil {
		t.Fatalf("NewTLSConfig(%q, pin len %d): %v", caFile, len(pin), err)
	}
	return cfg
}

// CHK-M4-040 (CHK-M4-322, -323, -325, -326): each refused with zero request
// bytes reaching the handler.
func TestTLSRefused(t *testing.T) {
	p := newPKI(t)
	other := newLeaf(t, p.a, local()) // same CA, different key
	cases := []struct {
		name    string
		srv     leaf
		minV    uint16
		maxV    uint16
		pin     string
		wantPin bool // the refusal must be the pin check
	}{
		{"leaf from untrusted CA B", p.fromB, 0, 0, "", false},
		{"wrong host name", p.wrongHost, 0, 0, "", false},
		{"expired leaf", p.expired, 0, 0, "", false},
		{"not-yet-valid leaf", p.notYet, 0, 0, "", false},
		{"TLS 1.1-only server", p.good, tls.VersionTLS10, tls.VersionTLS11, "", false},
		{"TLS 1.0-only server", p.good, tls.VersionTLS10, tls.VersionTLS10, "", false},
		{"right chain, wrong pin (another key)", p.good, 0, 0, pinOf(other.cert), true},
		{"right chain, pin of CA A", p.good, 0, 0, pinOf(p.a.cert), true},
		{"intermediate chain, pin of the intermediate (#79: leaf only)", p.viaInter, 0, 0, pinOf(p.inter.cert), true},
		{"intermediate chain, pin of the root", p.viaInter, 0, 0, pinOf(p.a.cert), true},
		{"untrusted CA B with B leaf's own pin (pin never replaces verification)", p.fromB, 0, 0, pinOf(p.fromB.cert), false},
		{"wrong host name with its own right pin", p.wrongHost, 0, 0, pinOf(p.wrongHost.cert), false},
		{"expired leaf with its own right pin", p.expired, 0, 0, pinOf(p.expired.cert), false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			s := newServer(t, tc.srv, tc.minV, tc.maxV, tls.NoClientCert)
			_, err := post(mustConfig(t, p.aFile, tc.pin), s.URL)
			if err == nil {
				t.Fatal("connection accepted")
			}
			if s.calls.Load() != 0 || s.bodyBytes.Load() != 0 {
				t.Fatalf("handler reached: %d calls, %d body bytes", s.calls.Load(), s.bodyBytes.Load())
			}
			if tc.wantPin != errors.Is(err, transport.ErrPinMismatch) {
				t.Fatalf("pin mismatch error = %v, want %v (err %v)", errors.Is(err, transport.ErrPinMismatch), tc.wantPin, err)
			}
			if tc.pin != "" && strings.Contains(strings.ToLower(err.Error()), tc.pin) {
				t.Fatalf("error echoes the pin: %v", err)
			}
		})
	}
}

// The TLS 1.1 refusal is real: a client that allows 1.0–1.1 does reach that
// server, so the server is not simply broken.
func TestTLS11ServerControl(t *testing.T) {
	p := newPKI(t)
	s := newServer(t, p.good, tls.VersionTLS10, tls.VersionTLS11, tls.NoClientCert)
	pool := x509.NewCertPool()
	pool.AddCert(p.a.cert)
	resp, err := post(oldClient(pool, tls.VersionTLS10, tls.VersionTLS11), s.URL)
	if err != nil {
		t.Skipf("this Go cannot speak TLS 1.1 at all (%v); the refusal case is then trivially true", err)
	}
	if resp.TLS.Version != tls.VersionTLS11 {
		t.Fatalf("control negotiated %x", resp.TLS.Version)
	}
}

// oldClient is the TLS 1.0–1.1 control client (versions as parameters).
func oldClient(pool *x509.CertPool, minV, maxV uint16) *tls.Config {
	return &tls.Config{RootCAs: pool, MinVersion: minV, MaxVersion: maxV}
}

// CHK-M4-041: accepted cases, and the negotiated version.
func TestTLSAccepted(t *testing.T) {
	p := newPKI(t)
	cases := []struct {
		name      string
		srv       leaf
		minV      uint16
		maxV      uint16
		pin       string
		wantVer   uint16
		serverNam string
	}{
		{"trusted chain, no pin, TLS 1.3 negotiated", p.good, 0, 0, "", tls.VersionTLS13, ""},
		{"right pin, lowercase", p.good, 0, 0, pinOf(p.good.cert), tls.VersionTLS13, ""},
		{"right pin, uppercase", p.good, 0, 0, strings.ToUpper(pinOf(p.good.cert)), tls.VersionTLS13, ""},
		{"intermediate chain with the leaf's pin", p.viaInter, 0, 0, pinOf(p.viaInter.cert), tls.VersionTLS13, ""},
		{"TLS 1.2-only server", p.good, tls.VersionTLS12, tls.VersionTLS12, pinOf(p.good.cert), tls.VersionTLS12, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			s := newServer(t, tc.srv, tc.minV, tc.maxV, tls.NoClientCert)
			resp, err := post(mustConfig(t, p.aFile, tc.pin), s.URL)
			if err != nil {
				t.Fatalf("refused: %v", err)
			}
			if resp.TLS == nil || resp.TLS.Version != tc.wantVer {
				t.Fatalf("version %x, want %x", resp.TLS.Version, tc.wantVer)
			}
			if s.calls.Load() != 1 || s.bodyBytes.Load() != int64(len(`{"canary":"BODY-CANARY"}`)) {
				t.Fatalf("handler: %d calls, %d bytes", s.calls.Load(), s.bodyBytes.Load())
			}
		})
	}
	// a ca_file with several CAs (A and B): both chains verify
	both := writePEM(t, p.dir, "ab.pem", p.b, p.a)
	for _, l := range []leaf{p.good, p.fromB} {
		s := newServer(t, l, 0, 0, tls.NoClientCert)
		if _, err := post(mustConfig(t, both, ""), s.URL); err != nil {
			t.Fatalf("bundle with A and B refused %s: %v", l.cert.Issuer.CommonName, err)
		}
	}
	// serverName passed through: connect to 127.0.0.1 but verify as localhost
	sLocal := newServer(t, newLeaf(t, p.a, leafOpt{dns: []string{"localhost"}}), 0, 0, tls.NoClientCert)
	cfg, err := transport.NewTLSConfig(p.aFile, "", "localhost")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := post(cfg, sLocal.URL); err != nil {
		t.Fatalf("serverName localhost refused: %v", err)
	}
	if _, err := post(mustConfig(t, p.aFile, ""), sLocal.URL); err == nil {
		t.Fatal("a DNS-only leaf accepted for an IP URL without serverName")
	}
}

// CHK-M4-044: no client certificate, even when the server asks for one.
func TestTLSNoClientCertificate(t *testing.T) {
	p := newPKI(t)
	for _, auth := range []tls.ClientAuthType{tls.RequestClientCert, tls.VerifyClientCertIfGiven} {
		s := newServer(t, p.good, 0, 0, auth)
		if _, err := post(mustConfig(t, p.aFile, pinOf(p.good.cert)), s.URL); err != nil {
			t.Fatalf("auth %v: %v", auth, err)
		}
		if s.clientCerts.Load() != 0 {
			t.Fatalf("auth %v: server saw %d client certificates", auth, s.clientCerts.Load())
		}
	}
	// a server that requires one refuses the agent (it never presents one)
	s := newServer(t, p.good, 0, 0, tls.RequireAnyClientCert)
	if _, err := post(mustConfig(t, p.aFile, ""), s.URL); err == nil {
		t.Fatal("a server requiring a client certificate accepted the agent")
	}
	for _, pin := range []string{"", pinOf(p.good.cert)} {
		for _, caFile := range []string{"", p.aFile} {
			cfg := mustConfig(t, caFile, pin)
			if len(cfg.Certificates) != 0 || cfg.GetClientCertificate != nil || cfg.GetCertificate != nil {
				t.Fatalf("client certificate configured (ca %q pin %v)", caFile, pin != "")
			}
		}
	}
}

// CHK-M4-045: the configuration itself.
func TestTLSConfigFields(t *testing.T) {
	p := newPKI(t)
	for _, pin := range []string{"", pinOf(p.good.cert)} {
		for _, caFile := range []string{"", p.aFile} {
			cfg := mustConfig(t, caFile, pin)
			if cfg.MinVersion < tls.VersionTLS12 {
				t.Errorf("MinVersion %x", cfg.MinVersion)
			}
			if cfg.MaxVersion != 0 && cfg.MaxVersion < tls.VersionTLS13 {
				t.Errorf("MaxVersion %x caps TLS 1.3", cfg.MaxVersion)
			}
			// read by reflection: the lint bans the selector even in tests
			if reflect.ValueOf(cfg).Elem().FieldByName("Insecure" + "SkipVerify").Bool() {
				t.Error("InsecureSkipVerify set")
			}
			if cfg.VerifyPeerCertificate != nil {
				t.Error("VerifyPeerCertificate set (could replace verification)")
			}
			if (caFile == "") != (cfg.RootCAs == nil) {
				t.Errorf("ca_file %q: RootCAs nil = %v", caFile, cfg.RootCAs == nil)
			}
			if (pin != "") != (cfg.VerifyConnection != nil) {
				t.Errorf("pin set %v: VerifyConnection set %v", pin != "", cfg.VerifyConnection != nil)
			}
		}
	}
	// VerifyConnection with no peer certificate refuses
	cfg := mustConfig(t, p.aFile, pinOf(p.good.cert))
	if err := cfg.VerifyConnection(tls.ConnectionState{}); !errors.Is(err, transport.ErrPinMismatch) {
		t.Fatalf("no peer certificate: %v", err)
	}
	if err := cfg.VerifyConnection(tls.ConnectionState{PeerCertificates: []*x509.Certificate{p.good.cert}}); err != nil {
		t.Fatalf("the leaf's pin: %v", err)
	}
	// only the first (leaf) certificate counts, even if a later one matches
	if err := cfg.VerifyConnection(tls.ConnectionState{PeerCertificates: []*x509.Certificate{p.fromB.cert, p.good.cert}}); !errors.Is(err, transport.ErrPinMismatch) {
		t.Fatalf("pin matched a non-leaf certificate: %v", err)
	}
}

// CHK-M4-043, -046: bad inputs are configuration errors (no silent system store).
func TestTLSConfigErrors(t *testing.T) {
	p := newPKI(t)
	junk := filepath.Join(p.dir, "junk.pem")
	if err := os.WriteFile(junk, []byte("not a certificate\n-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	empty := filepath.Join(p.dir, "empty.pem")
	if err := os.WriteFile(empty, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	good := pinOf(p.good.cert)
	cases := map[string][2]string{
		"missing ca_file":           {filepath.Join(p.dir, "absent.pem"), ""},
		"ca_file without PEM cert":  {junk, ""},
		"empty ca_file":             {empty, ""},
		"ca_file is a directory":    {p.dir, ""},
		"pin 63 hex":                {p.aFile, good[:63]},
		"pin 65 hex":                {p.aFile, good + "0"},
		"pin 62 hex (31 bytes)":     {p.aFile, good[:62]},
		"pin 66 hex (33 bytes)":     {p.aFile, good + "00"},
		"pin with a non-hex char":   {p.aFile, "g" + good[1:]},
		"pin with colons":           {p.aFile, strings.Join(splitPairs(good), ":")},
		"pin base64":                {p.aFile, "q83vEjRWeJq83vEjRWeJq83vEjRWeJq83vEjRWeJq80="},
		"pin with spaces":           {p.aFile, " " + good[1:]},
		"pin of 64 non-hex letters": {p.aFile, strings.Repeat("z", 64)},
	}
	for name, in := range cases {
		t.Run(name, func(t *testing.T) {
			cfg, err := transport.NewTLSConfig(in[0], in[1], "")
			if err == nil || cfg != nil {
				t.Fatalf("accepted: cfg %v err %v", cfg != nil, err)
			}
			if in[1] != "" && strings.Contains(err.Error(), in[1]) {
				t.Fatalf("error echoes the pin: %v", err)
			}
			if strings.Contains(err.Error(), "\n") {
				t.Fatalf("multi-line error: %q", err)
			}
		})
	}
	if os.Geteuid() != 0 {
		unreadable := writePEM(t, p.dir, "secret.pem", p.a)
		if err := os.Chmod(unreadable, 0o000); err != nil {
			t.Fatal(err)
		}
		if _, err := transport.NewTLSConfig(unreadable, "", ""); err == nil {
			t.Fatal("unreadable ca_file accepted")
		}
	} else {
		t.Log("unreadable ca_file case runs in the non-root (bstester) run")
	}
}

func splitPairs(s string) []string {
	var out []string
	for i := 0; i+2 <= len(s); i += 2 {
		out = append(out, s[i:i+2])
	}
	return out
}

// CHK-M4-042 (CHK-M4-324): ca_file replaces the system store. TestMain
// (main_test.go) makes the process's system store exactly {sysCA} through
// SSL_CERT_FILE and an empty SSL_CERT_DIR, before any handshake.
func TestTLSCAFileReplacesSystemStore(t *testing.T) {
	p := newPKI(t)
	sSys := newServer(t, newLeaf(t, sysCA, local()), 0, 0, tls.NoClientCert)
	sA := newServer(t, p.good, 0, 0, tls.NoClientCert)
	// ca_file empty: the system store (sysCA) is used
	if _, err := post(mustConfig(t, "", ""), sSys.URL); err != nil {
		t.Fatalf("system store not used with ca_file empty: %v", err)
	}
	// ca_file = A: the system store's CA is not trusted any more (not appended)
	if _, err := post(mustConfig(t, p.aFile, ""), sSys.URL); err == nil {
		t.Fatal("ca_file A did not replace the system store")
	}
	// ca_file = A still trusts A
	if _, err := post(mustConfig(t, p.aFile, ""), sA.URL); err != nil {
		t.Fatalf("ca_file A refused A's leaf: %v", err)
	}
	// control: with the system store only, A's leaf is refused (A is not in it)
	if _, err := post(mustConfig(t, "", ""), sA.URL); err == nil {
		t.Fatal("control: CA A accepted from the system store")
	}
	if sSys.calls.Load() != 1 || sA.calls.Load() != 1 {
		t.Fatalf("handler calls: system-CA server %d (want 1), A server %d (want 1)", sSys.calls.Load(), sA.calls.Load())
	}
}
