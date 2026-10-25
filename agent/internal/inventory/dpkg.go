package inventory

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"slices"
	"strconv"
	"strings"

	"bitscan.local/agent/internal/agent/wire"
)

// Packages is the parsed dpkg-query list. Rows are kept exactly as dpkg
// printed them (#77 (d)); the counts go to raw.errors, never line content.
type Packages struct {
	Items    []wire.PackageItem
	BadLines int // lines without exactly 6 fields, skipped (lead ruling Q4)
	BadSizes int // Installed-Size not a decimal integer, sent as null (Q3)
}

// ListPackages runs dpkg-query (TS §3.4 L235) and parses its output. Any
// failure of the command is an error, so the caller uploads nothing: an
// empty list would make the manager drop every package of the host (Q2).
func ListPackages(ctx context.Context) (Packages, error) {
	out, err := dpkgQueryCmd.run(ctx)
	if err != nil {
		return Packages{}, fmt.Errorf("inventory: dpkg-query: %w", err)
	}
	return ParseDpkg(out), nil
}

// ParseDpkg parses lines of the TS §3.4 format: six tab-separated fields per
// line. An empty Source or Installed-Size is null.
func ParseDpkg(out []byte) Packages {
	p := Packages{Items: []wire.PackageItem{}}
	lines := strings.Split(string(out), "\n")
	if lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1] // the newline ending the last row
	}
	for _, line := range lines {
		f := strings.Split(line, "\t")
		if len(f) != 6 {
			p.BadLines++
			continue
		}
		for i := range f {
			f[i] = asEncoded(f[i])
		}
		item := wire.PackageItem{Name: f[0], Version: f[1], Architecture: f[2], Status: f[3]}
		if f[4] != "" {
			item.Source = &f[4]
		}
		if f[5] != "" {
			kb, err := strconv.ParseInt(f[5], 10, 64)
			if err == nil && strings.Trim(f[5], "0123456789") == "" {
				item.InstalledSizeKB = &kb
			} else {
				p.BadSizes++
			}
		}
		p.Items = append(p.Items, item)
	}
	return p
}

// asEncoded replaces each byte that is not valid UTF-8 with U+FFFD, as
// encoding/json does when it sends the string, so list_sha256 is computed
// over exactly the text the manager receives and rehashes.
func asEncoded(s string) string {
	if strings.ToValidUTF8(s, "") == s {
		return s
	}
	var b strings.Builder
	for _, r := range s { // ranging yields U+FFFD for each invalid byte
		b.WriteRune(r)
	}
	return b.String()
}

// ListSHA256 is TS §6.5 L1186's list_sha256: the UTF-8 lines
// name\tversion\tarchitecture\tstatus\n sorted by their bytes, concatenated,
// SHA-256, lowercase hex (the manager's decode.list_sha256).
func ListSHA256(items []wire.PackageItem) wire.SHA256Hex {
	lines := make([][]byte, 0, len(items))
	for _, p := range items {
		lines = append(lines, []byte(p.Name+"\t"+p.Version+"\t"+p.Architecture+"\t"+p.Status+"\n"))
	}
	slices.SortFunc(lines, bytes.Compare)
	h := sha256.New()
	for _, line := range lines {
		h.Write(line)
	}
	return wire.SHA256Hex(hex.EncodeToString(h.Sum(nil)))
}
