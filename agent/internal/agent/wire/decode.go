package wire

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"reflect"
	"strconv"
	"strings"
	"unicode/utf8"
)

// maxDepth is the manager decoder's container limit, counted from the body
// root (services/inventory/decode.py MAX_DEPTH; TASK-048 plan).
const maxDepth = 32

// checker is implemented by the named types that carry a format or enum rule.
type checker interface{ check() error }

var timeType = reflect.TypeFor[Time]()

// DecodeStrict decodes one JSON document into v and refuses anything the
// contract does not allow: an unknown or missing key (nullable keys must be
// present), null for a non-nullable key, a wrong type, a non-integer number
// for an integer, a value outside its bounds or format, and trailing data.
func DecodeStrict[T any](body []byte, v *T) error {
	if err := checkShape(body, reflect.TypeFor[T](), "body"); err != nil {
		return err
	}
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.UseNumber()
	if err := dec.Decode(v); err != nil {
		return fmt.Errorf("wire: decode: %w", err)
	}
	return Validate(v)
}

// Encode validates v (REQ-091 (2), the agent's self-check before sending) and
// returns its JSON without a trailing newline and without HTML escaping.
func Encode(v any) ([]byte, error) {
	if err := Validate(v); err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, fmt.Errorf("wire: encode: %w", err)
	}
	return bytes.TrimSuffix(buf.Bytes(), []byte("\n")), nil
}

// DecodeProblem reads a problem body leniently: problem bodies are not part
// of the strict contract and only type and status are used. A missing type
// means "about:blank" (RFC 9457).
func DecodeProblem(body []byte) (Problem, error) {
	var p Problem
	if err := json.Unmarshal(body, &p); err != nil {
		return Problem{}, fmt.Errorf("wire: problem: %w", err)
	}
	if p.Type == "" {
		p.Type = "about:blank"
	}
	return p, nil
}

func jsonName(f reflect.StructField) string {
	name, _, _ := strings.Cut(f.Tag.Get("json"), ",")
	if !f.IsExported() || name == "-" {
		return ""
	}
	return name
}

// checkShape walks the raw JSON with the Go type: exact key sets, and null
// only where the field is a pointer. Go's decoder alone cannot tell a missing
// key from null or a zero value.
func checkShape(raw []byte, t reflect.Type, path string) error {
	isNull := string(bytes.TrimSpace(raw)) == "null"
	if t.Kind() == reflect.Pointer {
		if isNull {
			return nil
		}
		t = t.Elem()
	} else if isNull {
		return fmt.Errorf("wire: %s: null not allowed", path)
	}
	switch {
	case t == timeType:
	case t.Kind() == reflect.Struct:
		var obj map[string]json.RawMessage
		if err := json.Unmarshal(raw, &obj); err != nil {
			return fmt.Errorf("wire: %s: want an object: %w", path, err)
		}
		var kind string
		_ = json.Unmarshal(obj["kind"], &kind) // only for only=<kind> keys; kind is checked itself
		used := 0
		for i := range t.NumField() {
			f := t.Field(i)
			name := jsonName(f)
			if name == "" {
				continue
			}
			fr := parseRule(f.Tag.Get("wire"))
			only := fr.only
			val, present := obj[name]
			wanted := only == "" || only == kind
			switch {
			case present && !wanted:
				return fmt.Errorf("wire: %s.%s: key not allowed here", path, name)
			case !present && wanted && fr.opt:
			case !present && wanted:
				return fmt.Errorf("wire: %s.%s: missing key", path, name)
			case present && fr.opt && string(bytes.TrimSpace(val)) == "null":
				return fmt.Errorf("wire: %s.%s: null not allowed", path, name)
			case present:
				used++
				if err := checkShape(val, f.Type, path+"."+name); err != nil {
					return err
				}
			}
		}
		if used != len(obj) {
			return fmt.Errorf("wire: %s: unknown key", path)
		}
	case t.Kind() == reflect.Slice:
		var items []json.RawMessage
		if err := json.Unmarshal(raw, &items); err != nil {
			return fmt.Errorf("wire: %s: want an array: %w", path, err)
		}
		for _, item := range items {
			if err := checkShape(item, t.Elem(), path+"[]"); err != nil {
				return err
			}
		}
	case t.Kind() == reflect.Map:
		var obj map[string]json.RawMessage
		if err := json.Unmarshal(raw, &obj); err != nil {
			return fmt.Errorf("wire: %s: want an object: %w", path, err)
		}
	}
	return nil
}

type rule struct {
	min, max       int64
	hasMin, hasMax bool
	nul, uniq      bool
	only           string
	// opt: the key may be absent (a pointer field, nil then); present, it
	// must not be null. For keys a newer peer adds (TS §6.5).
	opt bool
}

func parseRule(tag string) rule {
	var r rule
	for _, part := range strings.Split(tag, ",") {
		key, val, _ := strings.Cut(part, "=")
		n, _ := strconv.ParseInt(val, 10, 64) // tags are constants in wire.go
		switch key {
		case "min":
			r.min, r.hasMin = n, true
		case "max":
			r.max, r.hasMax = n, true
		case "nul":
			r.nul = true
		case "uniq":
			r.uniq = true
		case "only":
			r.only = val
		case "opt":
			r.opt = true
		}
	}
	return r
}

func (r rule) bounds(n int64, path string) error {
	if (r.hasMin && n < r.min) || (r.hasMax && n > r.max) {
		return fmt.Errorf("wire: %s: out of range", path)
	}
	return nil
}

// Validate checks the bounds, formats and variant rules of a contract value.
// A non-pointer slice or map must not be nil, because it would encode as null.
func Validate(v any) error {
	return validate(reflect.ValueOf(v), rule{}, 1, "body")
}

func validate(v reflect.Value, r rule, level int, path string) error {
	if !v.IsValid() {
		return fmt.Errorf("wire: %s: no value", path)
	}
	if v.Kind() == reflect.Pointer {
		if v.IsNil() {
			return nil
		}
		return validate(v.Elem(), r, level, path)
	}
	if c, ok := v.Interface().(checker); ok {
		if err := c.check(); err != nil {
			return fmt.Errorf("wire: %s: %w", path, err)
		}
	}
	switch v.Kind() {
	case reflect.Struct:
		if v.Type() == timeType {
			return nil
		}
		for i := range v.NumField() {
			f := v.Type().Field(i)
			name := jsonName(f)
			if name == "" {
				continue
			}
			fr, fv := parseRule(f.Tag.Get("wire")), v.Field(i)
			if fr.only == "" && (fv.Kind() == reflect.Slice || fv.Kind() == reflect.Map) && fv.IsNil() {
				return fmt.Errorf("wire: %s.%s: must not be null", path, name)
			}
			if err := validate(fv, fr, level+1, path+"."+name); err != nil {
				return err
			}
		}
	case reflect.Slice:
		if err := r.bounds(int64(v.Len()), path); err != nil {
			return err
		}
		seen := map[any]bool{}
		for i := range v.Len() {
			item := v.Index(i)
			if r.uniq {
				if seen[item.Interface()] {
					return fmt.Errorf("wire: %s: duplicate item", path)
				}
				seen[item.Interface()] = true
			}
			if err := validate(item, rule{nul: r.nul}, level+1, path+"[]"); err != nil {
				return err
			}
		}
	case reflect.Map:
		return validateRaw(v.Interface(), level, path)
	case reflect.String:
		s := v.String()
		if err := r.bounds(int64(utf8.RuneCountInString(s)), path); err != nil {
			return err
		}
		if !r.nul && strings.ContainsRune(s, 0) {
			return fmt.Errorf("wire: %s: U+0000 not allowed", path)
		}
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		return r.bounds(v.Int(), path)
	}
	return nil
}

// validateRaw checks a RawValue tree: no U+0000 in keys or strings, finite
// numbers only, and no container deeper than maxDepth from the body root.
func validateRaw(x any, level int, path string) error {
	switch t := x.(type) {
	case map[string]any:
		if level > maxDepth {
			return fmt.Errorf("wire: %s: nested too deep", path)
		}
		for k, item := range t {
			if strings.ContainsRune(k, 0) {
				return fmt.Errorf("wire: %s: U+0000 not allowed", path)
			}
			if err := validateRaw(item, level+1, path); err != nil {
				return err
			}
		}
	case []any:
		if level > maxDepth {
			return fmt.Errorf("wire: %s: nested too deep", path)
		}
		for _, item := range t {
			if err := validateRaw(item, level+1, path); err != nil {
				return err
			}
		}
	case string:
		if strings.ContainsRune(t, 0) {
			return fmt.Errorf("wire: %s: U+0000 not allowed", path)
		}
	case json.Number:
		if f, err := strconv.ParseFloat(string(t), 64); err != nil || math.IsInf(f, 0) {
			return fmt.Errorf("wire: %s: number not finite", path)
		}
	case float64:
		if math.IsNaN(t) || math.IsInf(t, 0) {
			return fmt.Errorf("wire: %s: number not finite", path)
		}
	case bool, int, int64, nil:
	default:
		return fmt.Errorf("wire: %s: unsupported value type", path)
	}
	return nil
}
