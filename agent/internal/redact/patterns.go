package redact

import (
	"errors"
	"fmt"
	"regexp"
	"regexp/syntax"
)

var (
	ErrTooMany    = errors.New("redact: more than 50 patterns")
	ErrEmptyMatch = errors.New("redact: a pattern can match the empty string")
)

// PatternError names a refused pattern by its 0-based index in the list. Its
// Error text never holds the pattern: Go's compile errors quote it, so Err is
// reachable only through errors.Is, errors.As or Unwrap.
type PatternError struct {
	Index int
	Err   error
}

func (e *PatternError) Error() string { return fmt.Sprintf("redact: pattern %d refused", e.Index) }
func (e *PatternError) Unwrap() error { return e.Err }

// Set is a compiled pattern list, applied in list order. Use only a Set from
// Compile.
type Set struct{ res []*regexp.Regexp }

// Compile refuses the whole list (#134 (e)) when it has more than MaxPatterns
// entries, an entry Go's regexp cannot compile, or an entry that can match
// the empty string: no plugin runs with only part of a list (REQ-244). An
// empty list gives an empty Set; the cut-off rule still applies (#133).
func Compile(patterns []string) (*Set, error) {
	if len(patterns) > MaxPatterns {
		return nil, ErrTooMany
	}
	s := &Set{res: make([]*regexp.Regexp, 0, len(patterns))}
	for i, p := range patterns {
		re, err := regexp.Compile(p)
		if err != nil {
			return nil, &PatternError{Index: i, Err: err}
		}
		tree, err := syntax.Parse(p, syntax.Perl)
		if err != nil {
			return nil, &PatternError{Index: i, Err: err}
		}
		if nullable(tree.Simplify()) {
			return nil, &PatternError{Index: i, Err: ErrEmptyMatch}
		}
		s.res = append(s.res, re)
	}
	return s, nil
}

// nullable reports whether re can match the empty string. Zero-width
// assertions count as nullable, so a pattern that is only assertions is
// refused (it could insert markers and remove nothing).
func nullable(re *syntax.Regexp) bool {
	switch re.Op {
	case syntax.OpEmptyMatch, syntax.OpBeginLine, syntax.OpEndLine,
		syntax.OpBeginText, syntax.OpEndText, syntax.OpWordBoundary,
		syntax.OpNoWordBoundary, syntax.OpStar, syntax.OpQuest:
		return true
	case syntax.OpLiteral:
		return len(re.Rune) == 0
	case syntax.OpCapture, syntax.OpPlus:
		return nullable(re.Sub[0])
	case syntax.OpRepeat:
		return re.Min == 0 || nullable(re.Sub[0])
	case syntax.OpConcat:
		for _, sub := range re.Sub {
			if !nullable(sub) {
				return false
			}
		}
		return true
	case syntax.OpAlternate:
		for _, sub := range re.Sub {
			if nullable(sub) {
				return true
			}
		}
		return false
	}
	// OpNoMatch, OpCharClass, OpAnyChar, OpAnyCharNotNL: at least one rune
	// or no match at all.
	return false
}
