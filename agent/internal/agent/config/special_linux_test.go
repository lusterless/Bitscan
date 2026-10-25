package config_test

import (
	"path/filepath"
	"syscall"
	"testing"
)

// specialFiles returns ca_file values that are not regular files: a character
// device and a FIFO, which must be refused without blocking (opening a FIFO
// for reading waits for a writer).
func specialFiles(t *testing.T, dir string) map[string]string {
	t.Helper()
	fifo := filepath.Join(dir, "fifo.pem")
	if err := syscall.Mkfifo(fifo, 0o644); err != nil {
		t.Fatal(err)
	}
	return map[string]string{
		"a character device":      "/dev/null",
		"a FIFO (must not block)": fifo,
	}
}
