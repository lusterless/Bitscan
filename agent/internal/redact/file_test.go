package redact

import (
	"bytes"
	"testing"
)

func TestApplyFileRedactsTheWholeFile(t *testing.T) {
	s, err := Compile([]string{`password=\S+`})
	if err != nil {
		t.Fatal(err)
	}
	// Past every per-stream cap: the secret at the end is still redacted.
	data := append(bytes.Repeat([]byte("x"), 3*ReadLimit), []byte("\npassword=hunter2\n")...)
	got, cut := s.ApplyFile(data, 64<<20)
	if cut || bytes.Contains(got, []byte("hunter2")) || !bytes.HasSuffix(got, []byte("\n"+Marker+"\n")) {
		t.Fatalf("cut %v, tail %q", cut, got[len(got)-30:])
	}
}

func TestApplyFileCutOffKeyAndUTF8(t *testing.T) {
	s, _ := Compile(nil)
	got, _ := s.ApplyFile([]byte("ok \xff\n-----BEGIN RSA PRIVATE KEY-----\nMIIE"), 1<<20)
	if string(got) != "ok �\n"+Marker {
		t.Fatalf("got %q", got)
	}
}

func TestApplyFileCutsAtARuneBoundary(t *testing.T) {
	s, _ := Compile(nil)
	got, cut := s.ApplyFile([]byte("aé"), 2)
	if !cut || string(got) != "a" {
		t.Fatalf("got %q cut %v", got, cut)
	}
	got, cut = s.ApplyFile([]byte("abc"), 3)
	if cut || string(got) != "abc" {
		t.Fatalf("got %q cut %v", got, cut)
	}
}

func TestApplyFileFailsClosedOnGrowth(t *testing.T) {
	s, _ := Compile([]string{`a`})
	got, _ := s.ApplyFile(bytes.Repeat([]byte("a"), GrowthLimit), 64<<20)
	if string(got) != Marker {
		t.Fatalf("got %d bytes", len(got))
	}
}
