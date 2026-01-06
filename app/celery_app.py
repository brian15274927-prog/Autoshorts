"""
Celery application configuration.
Production-ready settings for video rendering workers.
"""
from celery import Celery
from kombu import Queue

CELERY_BROKER_URL = "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = "redis://localhost:6379/1"

celery_app = Celery(
    "video_rendering",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["app.rendering.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    task_track_started=True,
    task_time_limit=3600,
    task_soft_time_limit=3300,

    worker_prefetch_multiplier=1,
    worker_concurrency=2,

    task_acks_late=True,
    task_reject_on_worker_lost=True,

    result_expires=86400,
    result_extended=True,

    task_queues=(
        Queue("default", routing_key="default"),
        Queue("rendering", routing_key="rendering.#"),
    ),
    task_default_queue="default",
    task_default_exchange="tasks",
    task_default_routing_key="default",

    task_routes={
        "rendering.render_video": {"queue": "rendering"},
        "rendering.*": {"queue": "rendering"},
    },

    beat_schedule={
        "cleanup-old-outputs": {
            "task": "rendering.cleanup_old_outputs",
            "schedule": 3600.0,
            "kwargs": {"output_dir": "/tmp/video_output", "max_age_hours": 24},
        },
    },
)

celery_app.conf.broker_transport_options = {
    "visibility_timeout": 43200,
    "socket_timeout": 30,
    "socket_connect_timeout": 30,
}
