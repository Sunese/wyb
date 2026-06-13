package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/trace"
)

// mockPublisher captures published events and can be configured to fail.
type mockPublisher struct {
	mu     sync.Mutex
	events []TransactionImportedEvent
	err    error
}

func (m *mockPublisher) PublishTransactionImported(_ context.Context, tracer trace.Tracer, events ...TransactionImportedEvent) error {
	if m.err != nil {
		return m.err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.events = append(m.events, events...)
	return nil
}

func (m *mockPublisher) count() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.events)
}

// copyFile copies src to dst.
func copyFile(t *testing.T, src, dst string) {
	t.Helper()
	data, err := os.ReadFile(src)
	if err != nil {
		t.Fatalf("copyFile read %s: %v", src, err)
	}
	if err := os.WriteFile(dst, data, 0o644); err != nil {
		t.Fatalf("copyFile write %s: %v", dst, err)
	}
}

func TestReplayHandler_PublishesEventsFromRawDir(t *testing.T) {
	rawDir := t.TempDir()
	copyFile(t, "../../testdata/danskebank_salary_20250101_20251231.csv",
		filepath.Join(rawDir, "salary.csv"))

	pub := &mockPublisher{}
	handler := replayHandler(rawDir, pub, otel.Tracer("test"))

	req := httptest.NewRequest(http.MethodPost, "/replay", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}

	var body map[string]any
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("decode response: %v", err)
	}

	if got := int(body["files_replayed"].(float64)); got != 1 {
		t.Errorf("files_replayed = %d, want 1", got)
	}
	if got := int(body["events_published"].(float64)); got == 0 {
		t.Error("events_published = 0, want > 0")
	}
	errs := body["errors"]
	if errs != nil {
		t.Errorf("unexpected errors: %v", errs)
	}

	if pub.count() == 0 {
		t.Error("no events captured by publisher")
	}
}

func TestReplayHandler_SkipsDirectories(t *testing.T) {
	rawDir := t.TempDir()
	if err := os.Mkdir(filepath.Join(rawDir, "subdir"), 0o755); err != nil {
		t.Fatal(err)
	}
	copyFile(t, "../../testdata/danskebank_salary_20250101_20251231.csv",
		filepath.Join(rawDir, "salary.csv"))

	pub := &mockPublisher{}
	handler := replayHandler(rawDir, pub, otel.Tracer("test"))

	req := httptest.NewRequest(http.MethodPost, "/replay", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	var body map[string]any
	json.NewDecoder(rec.Body).Decode(&body)

	if got := int(body["files_replayed"].(float64)); got != 1 {
		t.Errorf("files_replayed = %d, want 1 (directory should be skipped)", got)
	}
}

func TestReplayHandler_ContinuesAfterParseError(t *testing.T) {
	rawDir := t.TempDir()

	// An unrecognised file that will fail to parse.
	if err := os.WriteFile(filepath.Join(rawDir, "garbage.csv"), []byte("not,a,bank,format\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	// A valid file that should still be processed.
	copyFile(t, "../../testdata/danskebank_salary_20250101_20251231.csv",
		filepath.Join(rawDir, "salary.csv"))

	pub := &mockPublisher{}
	handler := replayHandler(rawDir, pub, otel.Tracer("test"))

	req := httptest.NewRequest(http.MethodPost, "/replay", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	var body map[string]any
	json.NewDecoder(rec.Body).Decode(&body)

	if got := int(body["files_replayed"].(float64)); got != 1 {
		t.Errorf("files_replayed = %d, want 1", got)
	}
	errs, _ := body["errors"].([]any)
	if len(errs) != 1 {
		t.Errorf("errors = %v, want exactly 1 parse error", errs)
	}
	if pub.count() == 0 {
		t.Error("valid file should still produce events despite earlier parse error")
	}
}

func TestReplayHandler_SetsNonEmptyDedupKey(t *testing.T) {
	rawDir := t.TempDir()
	copyFile(t, "../../testdata/danskebank_salary_20250101_20251231.csv",
		filepath.Join(rawDir, "salary.csv"))

	pub := &mockPublisher{}
	handler := replayHandler(rawDir, pub, otel.Tracer("test"))

	req := httptest.NewRequest(http.MethodPost, "/replay", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}

	pub.mu.Lock()
	defer pub.mu.Unlock()
	for i, ev := range pub.events {
		if ev.DedupKey == "" {
			t.Errorf("event[%d] has empty DedupKey", i)
		}
	}

	// Keys must also be unique across events.
	seen := make(map[string]int)
	for i, ev := range pub.events {
		if prev, ok := seen[ev.DedupKey]; ok {
			t.Errorf("event[%d] and event[%d] share DedupKey %q", prev, i, ev.DedupKey)
		}
		seen[ev.DedupKey] = i
	}
}

func TestParseFile_HandlesArchivedFilename(t *testing.T) {
	rawDir := t.TempDir()
	// Simulate how the watcher archives files: timestamp prefix prepended.
	dst := filepath.Join(rawDir, "20260514T155959Z_salary.csv")
	copyFile(t, "../../testdata/danskebank_salary_20250101_20251231.csv", dst)

	rows, err := ParseFile(dst)
	if err != nil {
		t.Fatalf("ParseFile: %v", err)
	}
	if len(rows) == 0 {
		t.Fatal("expected rows")
	}
	if rows[0].AccountID != "salary" {
		t.Errorf("AccountID = %q, want %q", rows[0].AccountID, "salary")
	}
}
