package transport_test

import (
	"encoding/pem"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
)

// sysCA is the only CA in this test process's "system" store: TestMain points
// SSL_CERT_FILE at it and SSL_CERT_DIR at an empty directory before any
// handshake, so no test depends on the host's real CA store (CHK-M4-042).
var sysCA *ca

// proxyURL is a recording proxy set in every proxy variable for the whole
// test process; proxyConns counts the connections it receives (CHK-M4-082).
var (
	proxyURL   string
	proxyConns atomic.Int64
)

func TestMain(m *testing.M) {
	os.Exit(run(m))
}

func run(m *testing.M) int {
	dir, err := os.MkdirTemp("", "bitscan-transport-test-")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	defer func() { _ = os.RemoveAll(dir) }()
	sysCA, err = makeCA("system store CA", nil)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	bundle := filepath.Join(dir, "system.pem")
	if err := os.WriteFile(bundle, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: sysCA.der}), 0o600); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	empty := filepath.Join(dir, "certs")
	if err := os.Mkdir(empty, 0o700); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	if err := os.Setenv("SSL_CERT_FILE", bundle); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	if err := os.Setenv("SSL_CERT_DIR", empty); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	defer func() { _ = ln.Close() }()
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			proxyConns.Add(1)
			_ = conn.Close()
		}
	}()
	proxyURL = "http://" + ln.Addr().String()
	for _, k := range []string{"HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"} {
		if err := os.Setenv(k, proxyURL); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 2
		}
	}
	for _, k := range []string{"NO_PROXY", "no_proxy"} {
		if err := os.Unsetenv(k); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 2
		}
	}
	return m.Run()
}
