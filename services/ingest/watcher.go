package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"

	"github.com/fsnotify/fsnotify"
)

func startWatcher(ctx context.Context, dropDir, rawDir string, process func(ctx context.Context, path string) error) error {
	if err := os.MkdirAll(dropDir, 0o755); err != nil {
		return fmt.Errorf("create drop dir: %w", err)
	}
	if err := os.MkdirAll(rawDir, 0o755); err != nil {
		return fmt.Errorf("create raw dir: %w", err)
	}

	// Process anything already in drop/ before starting the watcher.
	// This makes ingest restartable — files dropped while it was down are not lost.
	if err := processExisting(ctx, dropDir, rawDir, process); err != nil {
		return fmt.Errorf("process existing: %w", err)
	}

	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return fmt.Errorf("create watcher: %w", err)
	}

	go func() {
		defer watcher.Close()
		for {
			select {
			case <-ctx.Done():
				return
			case event, ok := <-watcher.Events:
				if !ok {
					return
				}
				if event.Has(fsnotify.Create) {
					// Give the writer a moment to finish before we read.
					time.Sleep(200 * time.Millisecond)
					if err := handleFile(ctx, event.Name, rawDir, process); err != nil {
						slog.ErrorContext(ctx, "error handling file", "file", filepath.Base(event.Name), "err", err)
					}
				}
			case err, ok := <-watcher.Errors:
				if !ok {
					return
				}
				slog.ErrorContext(ctx, "watcher error", "err", err)
			}
		}
	}()

	if err := watcher.Add(dropDir); err != nil {
		return fmt.Errorf("watch %s: %w", dropDir, err)
	}

	slog.Info("watching drop directory", "dir", dropDir)
	return nil
}

func processExisting(ctx context.Context, dropDir, rawDir string, process func(ctx context.Context, path string) error) error {
	entries, err := os.ReadDir(dropDir)
	if err != nil {
		return fmt.Errorf("read dir: %w", err)
	}

	for _, entry := range entries {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if entry.IsDir() {
			continue
		}
		path := filepath.Join(dropDir, entry.Name())
		if err := handleFile(ctx, path, rawDir, process); err != nil {
			slog.ErrorContext(ctx, "error handling existing file", "file", entry.Name(), "err", err)
		}
	}
	return nil
}

func handleFile(ctx context.Context, path, rawDir string, process func(ctx context.Context, path string) error) error {
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("stat: %w", err)
	}
	if !info.Mode().IsRegular() {
		return nil
	}

	if err := process(ctx, path); err != nil {
		return fmt.Errorf("process: %w", err)
	}

	// Move to raw/ with a timestamp prefix — never modify, never delete.
	dest := filepath.Join(rawDir, time.Now().UTC().Format("20060102T150405Z_")+filepath.Base(path))
	if err := os.Rename(path, dest); err != nil {
		return fmt.Errorf("archive to %s: %w", dest, err)
	}

	slog.InfoContext(ctx, "archived file", "src", filepath.Base(path), "dest", filepath.Base(dest))
	return nil
}
