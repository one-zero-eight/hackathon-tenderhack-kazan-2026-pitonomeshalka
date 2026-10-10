"""Report upstream connectivity at startup without inference or index building."""

import asyncio
from datetime import datetime, timezone
import logging
from time import perf_counter

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("uvicorn.error")


def probe(service, base_url, path, model, timeout, make_client):
    started = perf_counter()
    record = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "service": service, "method": "GET", "url": base_url.rstrip("/") + path,
        "expected_model": model, "timeout_seconds": timeout,
    }
    try:
        info = make_client().health()
        actual_model = info.get("model") if service == "classifier" else info.get("id")
        if actual_model != model:
            raise ValueError(f"Expected model {model}, service returned {actual_model}")
        record.update(status="ok", details=info)
    except Exception as error:
        record.update(status="error", error=str(error), error_type=type(error).__name__)
    record["elapsed_seconds"] = round(perf_counter() - started, 3)
    if record["status"] == "ok":
        logger.info("Startup connection check: %s OK url=%s model=%s elapsed=%.3fs",
                    service, record["url"], model, record["elapsed_seconds"])
    else:
        logger.warning("Startup connection check: %s FAILED url=%s elapsed=%.3fs error=%s",
                       service, record["url"], record["elapsed_seconds"], record["error"])
    return record


async def check_connections(settings, client_factory, embedding_client_factory, store):
    classifier_timeout = min(settings.startup_check_timeout_seconds, settings.classifier_health_timeout_seconds,
                             settings.classifier_timeout_seconds)
    embedding_timeout = min(settings.startup_check_timeout_seconds, settings.embedding_timeout_seconds)
    results = await asyncio.gather(
        run_in_threadpool(probe, "classifier", settings.classifier_base_url, "/health", settings.classifier_model,
                          classifier_timeout, lambda: client_factory(settings.classifier_base_url, classifier_timeout)),
        run_in_threadpool(probe, "embedder", settings.embedding_base_url, "/models", settings.embedding_model,
                          embedding_timeout, lambda: embedding_client_factory(
                              settings.embedding_base_url, settings.embedding_model, embedding_timeout)),
    )
    await run_in_threadpool(store.save_connection_checks, results)
    logger.info("Startup connection results saved to PostgreSQL")
    return results
