// Package inventory collects and watches the host inventory (TS §3.4). This
// file is the dpkg watcher's debounce (#80); watch_linux.go is its inotify
// source.
package inventory

import (
	"context"
	"errors"
	"fmt"
	"time"

	"bitscan.local/agent/internal/agent/schedule"
)

const (
	// DpkgDir is watched as a directory because dpkg replaces status by
	// renaming a new file onto it (TS §3.4 L239).
	DpkgDir = "/var/lib/dpkg"
	// Quiet is how long no further change must arrive before a signal (#80).
	Quiet = 60 * time.Second
	// HoldOff is the least time between two signals: the manager's 10 minutes
	// plus a 30 s margin for clock and latency differences (#80).
	HoldOff = 10*time.Minute + 30*time.Second
)

// dirWatch reports changes to <dir>/status. Wait blocks until at least one
// change (nil) or a failure; Close makes a blocked Wait return an error.
type dirWatch interface {
	Wait() error
	Close() error
}

// openWatch is set by watch_linux.go; elsewhere the watch cannot be set.
var openWatch = func(string) (dirWatch, error) {
	return nil, errors.New("inventory: inotify is not available on this system")
}

// Watcher signals when the dpkg status file changed, debounced per #80.
type Watcher struct {
	dir   string
	clock schedule.Clock
}

// NewWatcher watches dir (DpkgDir in production) on clock.
func NewWatcher(dir string, clock schedule.Clock) *Watcher {
	return &Watcher{dir: dir, clock: clock}
}

// Run sets the watch and sends one value on out per debounced change until
// ctx is done. A watch that cannot be set, or fails later, is returned as an
// error for the caller to log; scheduled inventory does not depend on it.
// After a change it waits for Quiet without further changes, then signals if
// HoldOff has passed since the previous signal, otherwise when it has. A
// change during the wait or the hold-off is never lost.
func (w *Watcher) Run(ctx context.Context, out chan<- struct{}) error {
	dw, err := openWatch(w.dir)
	if err != nil {
		return err
	}
	defer func() { _ = dw.Close() }() // unblocks the reader below
	changes := make(chan struct{}, 1)
	failed := make(chan error, 1)
	go func() {
		for {
			if err := dw.Wait(); err != nil {
				failed <- err
				return
			}
			select { // changes not yet taken are merged into one
			case changes <- struct{}{}:
			default:
			}
		}
	}()
	return w.debounce(ctx, changes, failed, out)
}

func (w *Watcher) debounce(ctx context.Context, changes <-chan struct{}, failed <-chan error, out chan<- struct{}) error {
	var pending bool
	var quietUntil, last time.Time
	for {
		var fire <-chan time.Time
		if pending {
			at := quietUntil
			if !last.IsZero() && last.Add(HoldOff).After(at) {
				at = last.Add(HoldOff)
			}
			fire = w.clock.After(at.Sub(w.clock.Now()))
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case err := <-failed:
			return fmt.Errorf("inventory: dpkg watch stopped: %w", err)
		case <-changes:
			pending, quietUntil = true, w.clock.Now().Add(Quiet)
		case <-fire:
			select {
			case out <- struct{}{}:
			case <-ctx.Done():
				return ctx.Err()
			}
			pending, last = false, w.clock.Now()
		}
	}
}
