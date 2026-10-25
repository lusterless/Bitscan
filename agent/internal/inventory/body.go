package inventory

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"fmt"
	"maps"

	"bitscan.local/agent/internal/agent/wire"
)

// CollectBody collects the packages and os_info and builds the upload body.
// An error means nothing may be uploaded (ctx ended, or dpkg-query failed).
func CollectBody(ctx context.Context) ([]byte, error) {
	pkgs, err := ListPackages(ctx)
	if err != nil {
		return nil, err
	}
	info, err := CollectOSInfo(ctx)
	if err != nil {
		return nil, err
	}
	return BuildBody(info, pkgs)
}

// BuildBody returns the gzip-compressed (default level) compact JSON
// InventoryBody of TS §6.5 L1186; the caller sends it with
// Content-Encoding: gzip (#72 (a)). info is checked strictly with
// wire.Validate. The package rows are encoded without the field-bound check,
// exactly as dpkg printed them, so a row outside the contract is the
// manager's 422 and the agent's last_error, never a hidden package (#77 (d),
// lead ruling Q5). info is not modified.
func BuildBody(info wire.OsInfo, pkgs Packages) ([]byte, error) {
	raw := maps.Clone(info.Raw)
	if raw == nil {
		raw = map[string]any{}
	}
	errs := map[string]any{}
	if prev, ok := raw["errors"].(map[string]any); ok {
		errs = maps.Clone(prev)
	}
	if pkgs.BadLines > 0 {
		errs[dpkgQueryCmd.source] = fmt.Sprintf("%d lines not in the 6-field format", pkgs.BadLines)
	}
	if pkgs.BadSizes > 0 {
		errs["installed_size_kb"] = fmt.Sprintf("%d values not a decimal integer", pkgs.BadSizes)
	}
	fitRaw(raw, errs)
	info.Raw = raw
	if err := wire.Validate(info); err != nil {
		return nil, fmt.Errorf("inventory: os_info: %w", err)
	}
	items := pkgs.Items
	if items == nil {
		items = []wire.PackageItem{}
	}
	body := wire.InventoryBody{OsInfo: info, Packages: items, ListSHA256: ListSHA256(items)}
	var js bytes.Buffer
	enc := json.NewEncoder(&js)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(body); err != nil {
		return nil, fmt.Errorf("inventory: encode: %w", err)
	}
	var gz bytes.Buffer
	zw := gzip.NewWriter(&gz)
	if _, err := zw.Write(bytes.TrimSuffix(js.Bytes(), []byte("\n"))); err != nil {
		return nil, fmt.Errorf("inventory: gzip: %w", err)
	}
	if err := zw.Close(); err != nil {
		return nil, fmt.Errorf("inventory: gzip: %w", err)
	}
	return gz.Bytes(), nil
}
