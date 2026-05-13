package main

import (
	"context"
	"fmt"
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

	shutdown, err := initTracer(ctx)
	if err != nil {
		fmt.Printf("failed to init tracer: %v\n", err)
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

	mux.HandleFunc("/ping", func(w http.ResponseWriter, r *http.Request) {
		_, span := tracer.Start(r.Context(), "ingest.ping")
		defer span.End()
		fmt.Fprintln(w, "pong from ingest")
	})

	dropDir := os.Getenv("DROP_DIR")
	if dropDir == "" {
		fmt.Printf("DROP_DIR environment variable is required")
		os.Exit(1)
	}

	rawDir := os.Getenv("RAW_DIR")
	if rawDir == "" {
		fmt.Printf("RAW_DIR environment variable is required")
		os.Exit(1)
	}

	pub, err := newPublisher()
	if err != nil {
		fmt.Printf("failed to connect to RabbitMQ: %v\n", err)
		os.Exit(1)
	}
	defer pub.Close()

	processFile := func(ctx context.Context, path string) error {
		rows, err := ParseFile(path)
		if err != nil {
			return fmt.Errorf("parse: %w", err)
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
			if err := pub.Publish(ctx, event); err != nil {
				return fmt.Errorf("publish row %d: %w", row.RowIndex, err)
			}
		}
		fmt.Printf("published %d transactions from %s\n", len(rows), rows[0].SourceFile)
		return nil
	}

	if err := startWatcher(ctx, dropDir, rawDir, processFile); err != nil {
		fmt.Printf("failed to start watcher: %v\n", err)
		os.Exit(1)
	}

	port := os.Getenv("PORT")
	if port == "" {
		fmt.Printf("PORT environment variable is not set, defaulting to 8080")
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
		fmt.Printf("ingest listening on :%s\n", port)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			fmt.Printf("server error: %v\n", err)
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdownCtx)
}
