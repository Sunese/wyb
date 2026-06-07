package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/trace"
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

	pub, err := newPublisher()
	if err != nil {
		slog.Error("failed to connect to Kafka", "err", err)
		os.Exit(1)
	}
	defer pub.Close()

	mux.HandleFunc("/ping", func(w http.ResponseWriter, r *http.Request) {
		_, span := tracer.Start(r.Context(), "ingest.ping")
		defer span.End()

		// publish pong event
		pub.PublishPong(r.Context(), tracer, PongEvent{Message: "pong"})

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
		for _, row := range rows {
			rowCtx, publishSpan := tracer.Start(ctx, "ingest.publish",
				trace.WithSpanKind(trace.SpanKindProducer),
				trace.WithAttributes(
					attribute.Int("row.index", row.RowIndex),
					attribute.String("source.file", row.SourceFile),
				))
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
			publishErr := pub.PublishTransactionImported(rowCtx, tracer, event)
			publishSpan.End()
			if publishErr != nil {
				return fmt.Errorf("publish row %d: %w", row.RowIndex, publishErr)
			}
		}
		slog.InfoContext(ctx, "published transactions", "count", len(rows), "source_file", rows[0].SourceFile)
		return nil
	}

	mux.Handle("POST /replay", replayHandler(rawDir, pub, tracer))

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
