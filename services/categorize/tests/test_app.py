from unittest.mock import patch

from fastapi.testclient import TestClient

import categorize.main as main_module


class TestHealthEndpoint:
    def test_returns_200_ok(self):
        with patch("categorize.main.configure_tracing"), \
             patch("categorize.main.threading.Thread"):
            with TestClient(main_module.app) as client:
                response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_lifespan_starts_daemon_consumer_thread(self):
        with patch("categorize.main.configure_tracing"), \
             patch("categorize.main.threading.Thread") as mock_thread_cls:
            with TestClient(main_module.app):
                pass

        mock_thread_cls.assert_called_once_with(target=main_module.run_consumer, daemon=True)
        mock_thread_cls.return_value.start.assert_called_once()

    def test_lifespan_sets_stop_on_shutdown(self):
        with patch("categorize.main.configure_tracing"), \
             patch("categorize.main.threading.Thread"):
            with TestClient(main_module.app):
                assert not main_module._stop.is_set()

        assert main_module._stop.is_set()
