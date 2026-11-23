"""Optional telemetry remains disabled unless the user supplies configuration."""

from app.core.config import settings
from app.core.telemetry import configure_telemetry, langfuse_callback_handler, otlp_http_trace_endpoint


def test_otlp_endpoint_uses_http_trace_signal_path() -> None:
    assert otlp_http_trace_endpoint("http://collector:4318") == "http://collector:4318/v1/traces"
    assert otlp_http_trace_endpoint("https://collector.example/v1/traces/") == "https://collector.example/v1/traces"


def test_telemetry_stays_off_without_otlp_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", None)
    assert configure_telemetry() is False


def test_langfuse_callback_is_disabled_without_both_project_keys(monkeypatch) -> None:
    monkeypatch.setattr(settings, "langfuse_public_key", None)
    monkeypatch.setattr(settings, "langfuse_secret_key", None)
    assert langfuse_callback_handler() is None
