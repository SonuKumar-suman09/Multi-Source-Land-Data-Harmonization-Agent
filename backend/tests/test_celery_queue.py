"""Infra-independent checks for the Celery workflow task configuration."""

from app.tasks.celery_app import celery_app
from app.tasks.workflows import run_workflow_task


def test_workflow_task_is_registered_with_durable_queue_settings() -> None:
    assert run_workflow_task.name == "land_harmonizer.run_workflow"
    assert celery_app.conf.task_default_queue == "land_workflows"
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]

