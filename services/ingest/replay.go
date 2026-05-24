package main

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"

	"go.opentelemetry.io/otel/trace"
)

func replayHandler(rawDir string, pub eventPublisher, tracer trace.Tracer) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		_, span := tracer.Start(r.Context(), "ingest.replay")
		defer span.End()

		entries, err := os.ReadDir(rawDir)
		if err != nil {
			http.Error(w, fmt.Sprintf("read raw dir: %v", err), http.StatusInternalServerError)
			return
		}

		var filesReplayed, eventsPublished int
		var replayErrors []string

		for _, entry := range entries {
			if entry.IsDir() {
				continue
			}
			path := filepath.Join(rawDir, entry.Name())
			rows, err := ParseFile(path)
			if err != nil {
				replayErrors = append(replayErrors, fmt.Sprintf("%s: %v", entry.Name(), err))
				continue
			}
			for _, row := range rows {
				event := TransactionImportedEvent{
					SchemaVersion:  1,
					SourceFile:     row.SourceFile,
					RowIndex:       row.RowIndex,
					AccountID:      row.AccountID,
					Date:           row.Date.Format("2006-01-02"),
					AmountMinor:    row.AmountMinor,
					Currency:       row.Currency,
					RawDescription: row.Description,
				}
				if err := pub.Publish(r.Context(), event); err != nil {
					replayErrors = append(replayErrors, fmt.Sprintf("%s row %d: %v", entry.Name(), row.RowIndex, err))
					continue
				}
				eventsPublished++
			}
			filesReplayed++
		}

		slog.InfoContext(r.Context(), "replay complete",
			"files_replayed", filesReplayed,
			"events_published", eventsPublished,
			"errors", len(replayErrors),
		)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"files_replayed":   filesReplayed,
			"events_published": eventsPublished,
			"errors":           replayErrors,
		})
	}
}
