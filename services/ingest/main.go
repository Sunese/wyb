package main

import (
	"context"
	"crypto/sha256"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
)

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	shutdown, err := initTelemetry(ctx)
	if err != nil {
		slog.Error("failed to init telemetry", "err", err)
		os.Exit(1)
	}
	defer func() {
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = shutdown(shutdownCtx)
	}()

	tracer := otel.Tracer("ingest")

	mux := http.NewServeMux()

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintln(w, "ok")
	})

	dropDir := os.Getenv("DROP_DIR")
	if dropDir == "" {
		slog.Error("DROP_DIR environment variable is required")
		os.Exit(1)
	}

	rawDir := os.Getenv("RAW_DIR")
	if rawDir == "" {
		slog.Error("RAW_DIR environment variable is required")
		os.Exit(1)
	}

	importedPublisher, err := newPublisher("transaction.imported")
	if err != nil {
		slog.Error("failed to connect to Kafka", "err", err)
		os.Exit(1)
	}
	defer importedPublisher.Close()

	mux.HandleFunc("/ping", func(w http.ResponseWriter, r *http.Request) {
		_, span := tracer.Start(r.Context(), "ingest.ping")
		defer span.End()

		// publish pong event
		importedPublisher.PublishPong(r.Context(), tracer, PongEvent{Message: "pong"})

		slog.InfoContext(r.Context(), "received ping")
		fmt.Fprintln(w, "pong")
	})

	processFile := func(ctx context.Context, path string) error {
		ctx, span := tracer.Start(ctx, "ingest.processFile")
		defer span.End()
		rows, err := ParseFile(path)
		if err != nil {
			return fmt.Errorf("parse: %w", err)
		}
		events := rowsToEvents(rows)
		if err := importedPublisher.PublishTransactionImported(ctx, tracer, events...); err != nil {
			return fmt.Errorf("publish %s: %w", path, err)
		}
		slog.InfoContext(ctx, "published transactions", "count", len(rows), "source_file", rows[0].SourceFile)
		return nil
	}

	mux.Handle("POST /replay", replayHandler(rawDir, importedPublisher, tracer))

	if err := startWatcher(ctx, dropDir, rawDir, processFile); err != nil {
		slog.Error("failed to start watcher", "err", err)
		os.Exit(1)
	}

	port := os.Getenv("PORT")
	if port == "" {
		slog.Warn("PORT environment variable is not set, defaulting to 8080")
		port = "8080"
	}

	// Wrap the mux in otelhttp so every incoming request gets a span
	// and incoming traceparent headers are read.
	handler := otelhttp.NewHandler(mux, "ingest.http")

	server := &http.Server{
		Addr:    ":" + port,
		Handler: handler,
	}

	go func() {
		slog.Info("ingest listening", "port", port)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server error", "err", err)
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdownCtx)
}

func ComputeDedupKey(row Row) string {
	// Create a hash based on: account_id, date, amount_minor, currency, description
	json := fmt.Sprintf("%s|%s|%d|%s|%s", row.AccountID, row.Date.Format("2006-01-02"), row.AmountMinor, row.Currency, row.Description)
	return fmt.Sprintf("%x", sha256.Sum256([]byte(json)))
}
