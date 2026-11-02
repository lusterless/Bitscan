//go:build linux

// TASK-224 r2 (tester-m10c): sweep and cleanup errors reach the log as the
// operation and errno only, never a path a plugin named (TS §5.3, §8.4;
// REQ-251 (3)). The end-to-end half (the runner binary under systemd-run,
// its stderr grepped for the canary) is a TASK-228 row.
package main

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"strings"
	"syscall"
	"testing"
)

func TestPathlessDropsPaths(t *testing.T) {
	const canary = "M10PATHCANARY"
	pe := &fs.PathError{Op: "unlinkat", Path: "/tmp/" + canary + "-x/f", Err: syscall.EACCES}
	cases := []struct {
		name string
		err  error
		want string
	}{
		{"PathError", pe, "unlinkat: permission denied"},
		{"wrapped PathError", fmt.Errorf("runner: remove temp dir: %w", pe), "unlinkat: permission denied"},
		{"joined, canary text first", errors.Join(errors.New("cgroup "+canary+" busy"), fmt.Errorf("x: %w", pe)), "unlinkat: permission denied"},
		{"LinkError", &os.LinkError{Op: "rename", Old: "/tmp/" + canary, New: "/tmp/" + canary + "2", Err: syscall.EXDEV}, "invalid cross-device link"},
		{"PathError without an errno", &fs.PathError{Op: "readdir", Path: "/tmp/" + canary, Err: errors.New(canary + " gone")}, "readdir"},
		{"bare errno", fmt.Errorf("sweep: %w", syscall.EBUSY), "device or resource busy"},
		{"no errno", errors.New("sweep of " + canary + " timed out"), "no errno"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := pathless(tc.err)
			if got != tc.want {
				t.Errorf("pathless = %q, want %q", got, tc.want)
			}
			if strings.Contains(got, canary) || strings.Contains(got, "/tmp") {
				t.Errorf("pathless kept a path: %q", got)
			}
		})
	}
}
