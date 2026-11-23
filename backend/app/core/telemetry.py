"""Optional OpenTelemetry export and privacy-scoped Langfuse callbacks."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)
_provider_lock = threading.Lock()
_provider: Any | None = None
_langfuse_initialized = False
_langfuse_lock = threading.Lock()
_instrumented_services: set[str] = set()


def otlp_http_trace_endpoint(endpoint: str) -> str:
    """Normalize an OTLP/HTTP base URL to its trace signal endpoint."""
    normalized = endpoint.strip().rstrip("/")
    if not normalized:
        raise ValueError("OTLP endpoint cannot be empty")
    return normalized if normalized.endswith("/v1/traces") else f"{normalized}/v1/traces"


def configure_telemetry(app: Any | None = None, *, service_name: str | None = None) -> bool:
    """Enable OTLP instrumentation only when an endpoint was configured."""
    global _provider
    endpoint = settings.otel_exporter_otlp_endpoint
    if not endpoint:
        return False

    with _provider_lock:
        if _provider is None:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create({SERVICE_NAME: service_name or settings.otel_service_name})
            _provider = TracerProvider(resource=resource)
            _provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=otlp_http_trace_endpoint(endpoint))
                )
            )
            trace.set_tracer_provider(_provider)

        instrument_key = service_name or settings.otel_service_name
        if instrument_key not in _instrumented_services:
            from opentelemetry.instrumentation.celery import CeleryInstrumentor
            from opentelemetry.instrumentation.redis import RedisInstrumentor
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
            from app.database.session import engine

            SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=_provider)
            RedisInstrumentor().instrument(tracer_provider=_provider)
            CeleryInstrumentor().instrument(tracer_provider=_provider)
            _instrumented_services.add(instrument_key)

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        if not getattr(app.state, "otel_instrumented", False):
            FastAPIInstrumentor.instrument_app(app, tracer_provider=_provider)
            app.state.otel_instrumented = True
    logger.info("OpenTelemetry traces enabled for %s", service_name or settings.otel_service_name)
    return True


def langfuse_callback_handler() -> Any | None:
    """Return a LangChain callback only when both Langfuse credentials exist."""
    global _langfuse_initialized
    public_key = settings.langfuse_public_key.get_secret_value() if settings.langfuse_public_key else ""
    secret_key = settings.langfuse_secret_key.get_secret_value() if settings.langfuse_secret_key else ""
    if not public_key or not secret_key:
        return None

    with _langfuse_lock:
        if not _langfuse_initialized:
            from langfuse import Langfuse

            options = {"public_key": public_key, "secret_key": secret_key}
            if settings.langfuse_base_url:
                options["base_url"] = settings.langfuse_base_url
            Langfuse(**options)
            _langfuse_initialized = True

    from langfuse.langchain import CallbackHandler

    return CallbackHandler()
