// Package capread is the bitscan-capread helper (TS §3.7 L437–L484; #142).
// It answers exactly two request names, each with one fixed command run by
// absolute path. It never takes a command line, an argument or a path from a
// request, and the manager never enables it (it is enabled on the host).
package capread

// Socket is the helper's socket, created by bitscan-capread.socket.
const Socket = "/run/bitscan/capread.sock"

// commands is the whole table: the only processes capread ever starts.
var commands = map[string][]string{
	"nft_ruleset": {"/usr/sbin/nft", "-j", "list", "ruleset"},
	"audit_rules": {"/usr/sbin/auditctl", "-l"},
}

// Known reports whether name is one of the two request names.
func Known(name string) bool {
	_, ok := commands[name]
	return ok
}
