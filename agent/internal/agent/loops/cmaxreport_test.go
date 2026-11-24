package loops

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// Every check of the real ClusterMAX 0.3.0 report parses to one of the four
// verdict words with its Observed value (TS §3.8).
func TestEveryCheckOfTheReportParses(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "collector", "tests", "fixtures", "report-vm.txt"))
	if err != nil {
		t.Fatal(err)
	}
	report := string(raw)
	want := len(regexp.MustCompile(`(?m)^(PASS|FAIL|WARNING|SKIPPED|INFO)\s+.*\[[A-Za-z0-9_.-]+\]\s*$`).FindAllString(report, -1))
	got := parseCmaxChecks(report)
	if len(got) != want || want < 50 {
		t.Fatalf("%d checks parsed, %d in the report", len(got), want)
	}
	for id, text := range got {
		word, _, _ := strings.Cut(text, " ")
		if !map[string]bool{"PASS": true, "FAIL": true, "WARNING": true, "n/a": true}[word] || !strings.Contains(text, " observed=") {
			t.Errorf("%s: %q", id, text)
		}
	}
	if parseCmaxHeader("no block") != "MISSING no target block in the report" {
		t.Error("header without a block")
	}
	if cmaxErrorLine("x\ncmax: error: boom\n", 2) != "cmax: error: boom" || cmaxErrorLine("", 124) != "cmax exited 124" {
		t.Error("error line")
	}
}
