package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"

	"github.com/segmentio/kafka-go"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/trace"
)

type TransactionImportedEvent struct {
	SchemaVersion  int    `json:"schema_version"`
	SourceFile     string `json:"source_file"`
	RowIndex       int    `json:"row_index"`
	AccountID      string `json:"account_id"`
	Date           string `json:"date"`
	AmountMinor    int64  `json:"amount_minor"`
	Currency       string `json:"currency"`
	RawDescription string `json:"raw_description"`
}

type PongEvent struct {
	Message string `json:"message"`
}

// eventPublisher is the interface the replay handler depends on — lets tests inject a mock.
type eventPublisher interface {
	PublishTransactionImported(ctx context.Context, tracer trace.Tracer, event TransactionImportedEvent) error
}

type Writer struct {
	conn *kafka.Writer
}

func newPublisher() (*Writer, error) {
	url := os.Getenv("ConnectionStrings__kafka")
	if url == "" {
		slog.Error("ConnectionStrings__kafka environment variable is required")
		os.Exit(1)
	}

	topic := "my-topic"

	w := &kafka.Writer{
		Addr:                   kafka.TCP(url),
		Topic:                  topic,
		Balancer:               &kafka.LeastBytes{},
		AllowAutoTopicCreation: true,
	}

	return &Writer{conn: w}, nil
}

func (p *Writer) PublishTransactionImported(ctx context.Context, tracer trace.Tracer, event TransactionImportedEvent) error {
	data, err := json.Marshal(event)
	if err != nil {
		return err
	}

	err = p.conn.WriteMessages(ctx, kafka.Message{Value: data, Headers: injectTraceHeaders(ctx)})
	return err
}

func (p *Writer) PublishPong(ctx context.Context, tracer trace.Tracer, event PongEvent) error {
	data, err := json.Marshal(event)
	if err != nil {
		return err
	}

	_, span := tracer.Start(ctx, "writer manual span")
	span.SetAttributes(
		attribute.String("topic", p.conn.Topic),
		attribute.Int("message_size", len(data)),
		attribute.String("event_type", "pong"),
		attribute.String("event_message", event.Message),
	)
	span.AddLink(trace.LinkFromContext(ctx))
	fmt.Printf("Publishing pong event: %s\n", string(data))
	span.End()

	err = p.conn.WriteMessages(ctx, kafka.Message{Value: data, Headers: injectTraceHeaders(ctx)})
	return err
}

func (p *Writer) Close() {
	p.conn.Close()
}

func injectTraceHeaders(ctx context.Context) []kafka.Header {
	carrier := propagation.MapCarrier{}
	otel.GetTextMapPropagator().Inject(ctx, carrier)
	headers := make([]kafka.Header, 0, len(carrier))
	for k, v := range carrier {
		headers = append(headers, kafka.Header{Key: k, Value: []byte(v)})
	}
	return headers
}
