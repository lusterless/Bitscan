package inventory

import (
	"fmt"
	"syscall"
)

// uname(2) gives the values of `uname -r -m` without running a command (#35).
func init() {
	uname = func() (string, string, error) {
		var u syscall.Utsname
		if err := syscall.Uname(&u); err != nil {
			return "", "", fmt.Errorf("inventory: uname: %w", err)
		}
		return cString(u.Release[:]), cString(u.Machine[:]), nil
	}
}

// cString reads a NUL-terminated utsname field ([65]int8 on amd64).
func cString[T int8 | uint8](field []T) string {
	b := make([]byte, 0, len(field))
	for _, c := range field {
		if c == 0 {
			break
		}
		b = append(b, byte(c))
	}
	return string(b)
}
