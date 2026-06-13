import json
from unittest.mock import MagicMock, patch

import categorize.main as main_module
from categorize.main import (
    IN_TOPIC,
    OUT_TOPIC,
    _context_to_headers,
    _handle_message,
    _headers_to_carrier,
    run_consumer,
)


# ── _headers_to_carrier ───────────────────────────────────────────────────────

class TestHeadersToCarrier:
    def test_bytes_value_decoded(self):
        assert _headers_to_carrier([("traceparent", b"00-abc-def-01")]) == {"traceparent": "00-abc-def-01"}

    def test_bytearray_value_decoded(self):
        assert _headers_to_carrier([("key", bytearray(b"val"))]) == {"key": "val"}

    def test_string_value_passes_through(self):
        assert _headers_to_carrier([("key", "value")]) == {"key": "value"}

    def test_none_headers_returns_empty_dict(self):
        assert _headers_to_carrier(None) == {}

    def test_empty_list_returns_empty_dict(self):
        assert _headers_to_carrier([]) == {}

    def test_multiple_headers_all_included(self):
        assert _headers_to_carrier([("a", b"1"), ("b", b"2")]) == {"a": "1", "b": "2"}


# ── _context_to_headers ───────────────────────────────────────────────────────

class TestContextToHeaders:
    def test_returns_list_of_byte_tuples(self):
        with patch("categorize.main.propagate.inject",
                   side_effect=lambda c: c.update({"traceparent": "00-abc-def-01"})):
            result = _context_to_headers()

        assert isinstance(result, list)
        for k, v in result:
            assert isinstance(k, str)
            assert isinstance(v, bytes)

    def test_values_are_utf8_encoded(self):
        with patch("categorize.main.propagate.inject",
                   side_effect=lambda c: c.update({"x-custom": "hello"})):
            result = _context_to_headers()

        assert ("x-custom", b"hello") in result

    def test_empty_carrier_returns_empty_list(self):
        with patch("categorize.main.propagate.inject"):  # no-op, injects nothing
            result = _context_to_headers()

        assert result == []


# ── _handle_message ───────────────────────────────────────────────────────────

def _make_tracer():
    mock_span = MagicMock()
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
    mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
    return mock_tracer, mock_span


def _make_msg(body, headers=None):
    msg = MagicMock()
    msg.value.return_value = body.encode() if isinstance(body, str) else body
    msg.headers.return_value = headers or []
    return msg


class TestHandleMessage:
    def test_valid_message_produces_to_out_topic(self):
        payload = {"raw_description": "NETFLIX", "amount": 9900}
        enriched = {**payload, "category": "Subscriptions"}

        mock_tracer, _ = _make_tracer()
        mock_producer = MagicMock()

        with patch("categorize.main._enrich", return_value=(enriched, {})):
            _handle_message(_make_msg(json.dumps(payload)), mock_tracer, mock_producer)

        mock_producer.produce.assert_called_once()
        topic = mock_producer.produce.call_args[0][0]
        assert topic == OUT_TOPIC

    def test_produced_value_is_enriched_json(self):
        payload = {"raw_description": "NETFLIX", "amount": 9900}
        enriched = {**payload, "category": "Subscriptions", "merchant_name": "Netflix"}

        mock_tracer, _ = _make_tracer()
        mock_producer = MagicMock()

        with patch("categorize.main._enrich", return_value=(enriched, {})):
            _handle_message(_make_msg(json.dumps(payload)), mock_tracer, mock_producer)

        raw_value = mock_producer.produce.call_args[1]["value"]
        assert json.loads(raw_value) == enriched

    def test_string_message_value_handled(self):
        payload = {"raw_description": "X"}
        msg = MagicMock()
        msg.value.return_value = json.dumps(payload)  # str, not bytes
        msg.headers.return_value = []

        mock_tracer, _ = _make_tracer()
        mock_producer = MagicMock()

        with patch("categorize.main._enrich", return_value=({**payload, "category": "Uncategorized"}, {})):
            _handle_message(msg, mock_tracer, mock_producer)

        mock_producer.produce.assert_called_once()

    def test_invalid_json_skips_produce(self):
        mock_tracer, _ = _make_tracer()
        mock_producer = MagicMock()

        _handle_message(_make_msg("not {{ valid json"), mock_tracer, mock_producer)

        mock_producer.produce.assert_not_called()

    def test_none_body_skips_produce(self):
        msg = MagicMock()
        msg.value.return_value = None
        msg.headers.return_value = []

        mock_tracer, _ = _make_tracer()
        mock_producer = MagicMock()

        _handle_message(msg, mock_tracer, mock_producer)

        mock_producer.produce.assert_not_called()

    def test_span_attributes_set_from_enrich(self):
        payload = {"raw_description": "NETFLIX"}
        attrs = {"categorize.category": "Subscriptions", "categorize.matched_by": "rule"}

        mock_tracer, mock_span = _make_tracer()
        mock_producer = MagicMock()

        with patch("categorize.main._enrich",
                   return_value=({**payload, "category": "Subscriptions"}, attrs)):
            _handle_message(_make_msg(json.dumps(payload)), mock_tracer, mock_producer)

        mock_span.set_attribute.assert_any_call("categorize.category", "Subscriptions")
        mock_span.set_attribute.assert_any_call("categorize.matched_by", "rule")

    def test_producer_poll_called_after_produce(self):
        payload = {"raw_description": "X"}
        mock_tracer, _ = _make_tracer()
        mock_producer = MagicMock()

        with patch("categorize.main._enrich",
                   return_value=({**payload, "category": "Uncategorized"}, {})):
            _handle_message(_make_msg(json.dumps(payload)), mock_tracer, mock_producer)

        mock_producer.poll.assert_called_with(0)

    def test_trace_headers_attached_to_produced_message(self):
        payload = {"raw_description": "X"}
        mock_tracer, _ = _make_tracer()
        mock_producer = MagicMock()

        with patch("categorize.main._enrich",
                   return_value=({**payload, "category": "Uncategorized"}, {})), \
             patch("categorize.main._context_to_headers", return_value=[("traceparent", b"00-abc")]):
            _handle_message(_make_msg(json.dumps(payload)), mock_tracer, mock_producer)

        headers = mock_producer.produce.call_args[1]["headers"]
        assert headers == [("traceparent", b"00-abc")]


# ── run_consumer ──────────────────────────────────────────────────────────────

def _consumer_patches(mock_consumer, mock_producer):
    return (
        patch("categorize.main.Consumer", return_value=mock_consumer),
        patch("categorize.main.Producer", return_value=mock_producer),
        patch.dict("os.environ", {"ConnectionStrings__kafka": "localhost:9092"}),
    )


class TestRunConsumer:
    def test_stop_before_loop_skips_polling(self):
        main_module._stop.set()
        mock_consumer, mock_producer = MagicMock(), MagicMock()

        with patch("categorize.main.Consumer", return_value=mock_consumer), \
             patch("categorize.main.Producer", return_value=mock_producer), \
             patch.dict("os.environ", {"ConnectionStrings__kafka": "localhost:9092"}):
            run_consumer()

        mock_consumer.poll.assert_not_called()

    def test_consumer_subscribes_to_in_topic(self):
        main_module._stop.set()
        mock_consumer, mock_producer = MagicMock(), MagicMock()

        with patch("categorize.main.Consumer", return_value=mock_consumer), \
             patch("categorize.main.Producer", return_value=mock_producer), \
             patch.dict("os.environ", {"ConnectionStrings__kafka": "localhost:9092"}):
            run_consumer()

        mock_consumer.subscribe.assert_called_once_with([IN_TOPIC])

    def test_none_poll_result_continues_without_handling(self):
        mock_consumer, mock_producer = MagicMock(), MagicMock()

        def poll_then_stop(_timeout):
            main_module._stop.set()
            return None

        mock_consumer.poll.side_effect = poll_then_stop

        with patch("categorize.main.Consumer", return_value=mock_consumer), \
             patch("categorize.main.Producer", return_value=mock_producer), \
             patch("categorize.main._handle_message") as mock_handle, \
             patch.dict("os.environ", {"ConnectionStrings__kafka": "localhost:9092"}):
            run_consumer()

        mock_handle.assert_not_called()

    def test_message_with_error_is_skipped(self):
        mock_consumer, mock_producer = MagicMock(), MagicMock()
        mock_msg = MagicMock()
        mock_msg.error.return_value = MagicMock()  # truthy error

        def poll_then_stop(_timeout):
            main_module._stop.set()
            return mock_msg

        mock_consumer.poll.side_effect = poll_then_stop

        with patch("categorize.main.Consumer", return_value=mock_consumer), \
             patch("categorize.main.Producer", return_value=mock_producer), \
             patch("categorize.main._handle_message") as mock_handle, \
             patch.dict("os.environ", {"ConnectionStrings__kafka": "localhost:9092"}):
            run_consumer()

        mock_handle.assert_not_called()

    def test_valid_message_dispatched_to_handle_message(self):
        mock_consumer, mock_producer = MagicMock(), MagicMock()
        mock_msg = MagicMock()
        mock_msg.error.return_value = None

        def poll_then_stop(_timeout):
            main_module._stop.set()
            return mock_msg

        mock_consumer.poll.side_effect = poll_then_stop

        with patch("categorize.main.Consumer", return_value=mock_consumer), \
             patch("categorize.main.Producer", return_value=mock_producer), \
             patch("categorize.main._handle_message") as mock_handle, \
             patch.dict("os.environ", {"ConnectionStrings__kafka": "localhost:9092"}):
            run_consumer()

        mock_handle.assert_called_once()
        args = mock_handle.call_args[0]
        assert args[0] is mock_msg
        assert args[2] is mock_producer

    def test_handle_message_exception_does_not_wedge_consumer(self):
        mock_consumer, mock_producer = MagicMock(), MagicMock()
        mock_msg = MagicMock()
        mock_msg.error.return_value = None
        poll_count = 0

        def poll_side_effect(_timeout):
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 2:
                main_module._stop.set()
            return mock_msg

        mock_consumer.poll.side_effect = poll_side_effect

        with patch("categorize.main.Consumer", return_value=mock_consumer), \
             patch("categorize.main.Producer", return_value=mock_producer), \
             patch("categorize.main._handle_message", side_effect=Exception("boom")), \
             patch.dict("os.environ", {"ConnectionStrings__kafka": "localhost:9092"}):
            run_consumer()  # must not raise

        assert poll_count == 2

    def test_producer_flushed_on_shutdown(self):
        main_module._stop.set()
        mock_consumer, mock_producer = MagicMock(), MagicMock()

        with patch("categorize.main.Consumer", return_value=mock_consumer), \
             patch("categorize.main.Producer", return_value=mock_producer), \
             patch.dict("os.environ", {"ConnectionStrings__kafka": "localhost:9092"}):
            run_consumer()

        mock_producer.flush.assert_called_once_with(5)

    def test_consumer_closed_on_shutdown(self):
        main_module._stop.set()
        mock_consumer, mock_producer = MagicMock(), MagicMock()

        with patch("categorize.main.Consumer", return_value=mock_consumer), \
             patch("categorize.main.Producer", return_value=mock_producer), \
             patch.dict("os.environ", {"ConnectionStrings__kafka": "localhost:9092"}):
            run_consumer()

        mock_consumer.close.assert_called_once()
