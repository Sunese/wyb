package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestHandleFile_ArchivesAndCallsProcess(t *testing.T) {
	dropDir := t.TempDir()
	rawDir := t.TempDir()

	src := filepath.Join(dropDir, "salary.csv")
	if err := os.WriteFile(src, []byte("content"), 0o644); err != nil {
		t.Fatal(err)
	}

	var processed []string
	process := func(_ context.Context, path string) error {
		processed = append(processed, filepath.Base(path))
		return nil
	}

	if err := handleFile(context.Background(), src, rawDir, process); err != nil {
		t.Fatalf("handleFile: %v", err)
	}

	if len(processed) != 1 || processed[0] != "salary.csv" {
		t.Errorf("process called with %v, want [salary.csv]", processed)
	}

	// Original file should be gone.
	if _, err := os.Stat(src); !os.IsNotExist(err) {
		t.Error("source file should have been moved to raw/")
	}

	// Archived file should exist in rawDir with a timestamp prefix.
	entries, _ := os.ReadDir(rawDir)
	if len(entries) != 1 {
		t.Fatalf("rawDir has %d entries, want 1", len(entries))
	}
	name := entries[0].Name()
	if !strings.HasSuffix(name, "_salary.csv") {
		t.Errorf("archived name %q should end with _salary.csv", name)
	}
	if !archivedPrefix.MatchString(name) {
		t.Errorf("archived name %q should start with timestamp prefix", name)
	}
}

func TestHandleFile_SkipsDirectory(t *testing.T) {
	dropDir := t.TempDir()
	rawDir := t.TempDir()
	subdir := filepath.Join(dropDir, "subdir")
	if err := os.Mkdir(subdir, 0o755); err != nil {
		t.Fatal(err)
	}

	called := false
	process := func(_ context.Context, _ string) error {
		called = true
		return nil
	}

	if err := handleFile(context.Background(), subdir, rawDir, process); err != nil {
		t.Fatalf("handleFile: %v", err)
	}
	if called {
		t.Error("process should not be called for a directory")
	}
}

func TestProcessExisting_ProcessesAllFiles(t *testing.T) {
	dropDir := t.TempDir()
	rawDir := t.TempDir()

	for _, name := range []string{"a.csv", "b.csv"} {
		if err := os.WriteFile(filepath.Join(dropDir, name), []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Mkdir(filepath.Join(dropDir, "subdir"), 0o755); err != nil {
		t.Fatal(err)
	}

	var processed []string
	process := func(_ context.Context, path string) error {
		processed = append(processed, filepath.Base(path))
		return nil
	}

	if err := processExisting(context.Background(), dropDir, rawDir, process); err != nil {
		t.Fatalf("processExisting: %v", err)
	}

	if len(processed) != 2 {
		t.Errorf("processed %v, want 2 files (directory excluded)", processed)
	}
}

func TestProcessExisting_ContinuesAfterProcessError(t *testing.T) {
	dropDir := t.TempDir()
	rawDir := t.TempDir()

	for _, name := range []string{"a.csv", "b.csv"} {
		if err := os.WriteFile(filepath.Join(dropDir, name), []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	calls := 0
	process := func(_ context.Context, _ string) error {
		calls++
		if calls == 1 {
			return os.ErrPermission // simulate a parse/publish failure on the first file
		}
		return nil
	}

	// processExisting logs errors but does not stop — second file must be attempted.
	if err := processExisting(context.Background(), dropDir, rawDir, process); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if calls != 2 {
		t.Errorf("process called %d times, want 2", calls)
	}
}

func TestProcessExisting_RespectsContextCancellation(t *testing.T) {
	dropDir := t.TempDir()
	rawDir := t.TempDir()

	for _, name := range []string{"a.csv", "b.csv", "c.csv"} {
		if err := os.WriteFile(filepath.Join(dropDir, name), []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	ctx, cancel := context.WithCancel(context.Background())
	calls := 0
	process := func(_ context.Context, _ string) error {
		calls++
		cancel() // cancel after the first file
		return nil
	}

	err := processExisting(ctx, dropDir, rawDir, process)
	if err == nil {
		t.Error("expected context cancellation error")
	}
	if calls != 1 {
		t.Errorf("process called %d times after cancel, want 1", calls)
	}
}
