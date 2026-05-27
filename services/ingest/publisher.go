package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"time"

	"github.com/google/uuid"
	amqp "github.com/rabbitmq/amqp091-go"
	"go.opentelemetry.io/otel"
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

// eventPublisher is the interface the replay handler depends on — lets tests inject a mock.
type eventPublisher interface {
	Publish(ctx context.Context, event TransactionImportedEvent) error
}

type Publisher struct {
	conn    *amqp.Connection
	channel *amqp.Channel
}

func newPublisher() (*Publisher, error) {
	url := os.Getenv("ConnectionStrings__rabbit")
	if url == "" {
		return nil, fmt.Errorf("ConnectionStrings__rabbit is not set")
	}

	conn, err := amqp.Dial(url)
	if err != nil {
		return nil, fmt.Errorf("connect: %w", err)
	}

	ch, err := conn.Channel()
	if err != nil {
		conn.Close()
		return nil, fmt.Errorf("open channel: %w", err)
	}

	if err := ch.ExchangeDeclare(
		"transaction.imported",
		"fanout",
		true,  // durable
		false, // autoDelete
		false, // internal
		false, // noWait
		nil,
	); err != nil {
		return nil, fmt.Errorf("declare exchange: %w", err)
	}

	returns := ch.NotifyReturn(make(chan amqp.Return, 16))
	go func() {
		for r := range returns {
			slog.Warn("unroutable message returned",
				"reply_code", r.ReplyCode,
				"reply_text", r.ReplyText,
				"exchange", r.Exchange,
				"routing_key", r.RoutingKey,
				"message_id", r.MessageId,
			)
		}
	}()

	return &Publisher{conn: conn, channel: ch}, nil
}

func (p *Publisher) Publish(ctx context.Context, event TransactionImportedEvent) error {
	body, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}

	headers := amqp.Table{}
	otel.GetTextMapPropagator().Inject(ctx, amqpCarrier(headers))

	slog.InfoContext(ctx, "publishing message", "body", string(body))
	return p.channel.PublishWithContext(ctx,
		"transaction.imported",
		"",
		true, // mandatory: log a warning if no queue is bound
		false,
		amqp.Publishing{
			ContentType:  "application/json",
			DeliveryMode: amqp.Persistent,
			MessageId:    uuid.NewString(),
			Timestamp:    time.Now(),
			Headers:      headers,
			Body:         body,
		},
	)
}

func (p *Publisher) Close() {
	p.channel.Close()
	p.conn.Close()
}

// amqpCarrier wraps amqp.Table to satisfy otel's TextMapCarrier interface
// so trace context is propagated in message headers.
type amqpCarrier amqp.Table

func (c amqpCarrier) Get(key string) string {
	v, ok := c[key]
	if !ok {
		return ""
	}
	s, _ := v.(string)
	return s
}

func (c amqpCarrier) Set(key, value string) { c[key] = value }

func (c amqpCarrier) Keys() []string {
	keys := make([]string, 0, len(c))
	for k := range c {
		keys = append(keys, k)
	}
	return keys
}
