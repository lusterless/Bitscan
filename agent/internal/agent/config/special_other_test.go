//go:build !linux

package config_test

import "testing"

// specialFiles: device and FIFO cases run on Linux only (special_linux_test.go).
func specialFiles(t *testing.T, _ string) map[string]string {
	t.Helper()
	return nil
}
