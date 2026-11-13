// Package capread is the bitscan-capread helper (TS §3.7 L437–L486; #142).
// It answers exactly three request names: two run one fixed command each by
// absolute path, and one reads one fixed file itself. It never takes a
// command line, an argument or a path from a request, and the manager never
// enables it (it is enabled on the host).
package capread

// Socket is the helper's socket, created by bitscan-capread.socket.
const Socket = "/run/bitscan/capread.sock"

// commands are the only processes capread ever starts.
var commands = map[string][]string{
	"nft_ruleset": {"/usr/sbin/nft", "-j", "list", "ruleset"},
	"audit_rules": {"/usr/sbin/auditctl", "-l"},
}

// files are the only files capread reads for a request. The AppArmor list is
// opened only for uid or gid 0, so the unit adds the helper to group root
// (TS §3.7, §8.1 accepted risk).
var files = map[string]string{
	"apparmor_profiles": "/sys/kernel/security/apparmor/profiles",
}

// Known reports whether name is one of the request names.
func Known(name string) bool {
	_, cmd := commands[name]
	_, file := files[name]
	return cmd || file
}
