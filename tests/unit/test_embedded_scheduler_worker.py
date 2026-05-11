from __future__ import annotations

from types import SimpleNamespace

from t212ai.app.config import get_app_settings
from t212ai.app.scheduler_worker import build_embedded_scheduler_worker


def test_build_embedded_scheduler_worker_respects_settings() -> None:
    disabled_runtime = SimpleNamespace(
        settings=get_app_settings(env={"SCHEDULER_EMBEDDED_WORKER_ENABLED": "false"}),
        scheduled_process_service=object(),
    )
    assert build_embedded_scheduler_worker(disabled_runtime) is None

    unavailable_runtime = SimpleNamespace(
        settings=get_app_settings(env={"SCHEDULER_EMBEDDED_WORKER_ENABLED": "true"}),
        scheduled_process_service=None,
    )
    assert build_embedded_scheduler_worker(unavailable_runtime) is None

    enabled_runtime = SimpleNamespace(
        settings=get_app_settings(
            env={
                "SCHEDULER_EMBEDDED_WORKER_ENABLED": "true",
                "SCHEDULER_EMBEDDED_WORKER_POLL_EVERY_SECONDS": "30",
                "SCHEDULER_EMBEDDED_WORKER_LIMIT": "25",
                "SCHEDULER_LEASE_SECONDS": "1200",
                "SCHEDULER_STALE_RUN_AFTER_SECONDS": "2400",
                "SCHEDULER_MAX_LLM_RUNS_PER_PASS": "2",
            }
        ),
        scheduled_process_service=object(),
    )
    worker = build_embedded_scheduler_worker(enabled_runtime)

    assert worker is not None
    assert worker.poll_every_seconds == 30
    assert worker.limit == 25
    assert worker.lease_seconds == 1200
    assert worker.stale_run_after_seconds == 2400
    assert worker.max_llm_runs_per_pass == 2
