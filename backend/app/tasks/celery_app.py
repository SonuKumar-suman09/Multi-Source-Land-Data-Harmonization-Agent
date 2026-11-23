"""Celery application configured for durable Redis-backed job execution."""

from celery import Celery
from celery.signals import worker_process_init

from app.core.config import settings
from app.core.telemetry import configure_telemetry

celery_app = Celery(
    "land_harmonizer",
    broker=settings.redis_url,
    include=["app.tasks.workflows"],
)
celery_app.conf.update(
    task_default_queue=settings.celery_queue,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 7200},
    task_soft_time_limit=3540,
    task_time_limit=3600,
)


@worker_process_init.connect
def configure_worker_observability(**_: object) -> None:
    """Initialize exporters after Celery forks a worker child process."""
    configure_telemetry(service_name=f"{settings.otel_service_name}-worker")
