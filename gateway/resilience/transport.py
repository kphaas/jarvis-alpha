"""Shared Gateway egress transport resilience helpers.

Centralizes bounded retry with backoff + jitter, per-operation circuit
breakers, and DLQ recording for exhausted outbound failures.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

from fastapi import HTTPException
import httpx

from jarvis_common.logging_config import get_logger

from .circuit_breaker import CircuitBreaker, CircuitOpenError
from .dlq import DeadLetterQueue

logger = get_logger("alpha_gateway")

T = TypeVar("T")

_BREAKERS: dict[str, CircuitBreaker] = {}
_DLQS: dict[str, DeadLetterQueue] = {}
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class RetryableResponseError(Exception):
    """Raised internally when an upstream response should be retried."""

    def __init__(self, response: httpx.Response):
        self.response = response
        super().__init__(f"retryable upstream response status={response.status_code}")


def reset_resilience_state() -> None:
    """Clear cached breaker and DLQ registries. Test-only helper."""
    _BREAKERS.clear()
    _DLQS.clear()


def _bounded_int_env(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def _bounded_float_env(
    name: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def _retry_attempts() -> int:
    return _bounded_int_env(
        "GATEWAY_EGRESS_RETRY_ATTEMPTS",
        default=3,
        minimum=1,
        maximum=6,
    )


def _retry_delay_seconds(attempt: int) -> float:
    base_ms = _bounded_int_env(
        "GATEWAY_EGRESS_RETRY_BASE_MS",
        default=250,
        minimum=10,
        maximum=10_000,
    )
    max_ms = _bounded_int_env(
        "GATEWAY_EGRESS_RETRY_MAX_MS",
        default=2_000,
        minimum=50,
        maximum=30_000,
    )
    jitter_fraction = _bounded_float_env(
        "GATEWAY_EGRESS_RETRY_JITTER_FRACTION",
        default=0.2,
        minimum=0.0,
        maximum=1.0,
    )
    delay_ms = min(max_ms, base_ms * (2 ** max(attempt - 1, 0)))
    low = delay_ms * max(0.0, 1.0 - jitter_fraction)
    high = delay_ms * (1.0 + jitter_fraction)
    return random.uniform(low, high) / 1000.0


def _safe_queue_name(operation: str) -> str:
    safe = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in operation.lower()
    ).strip("-")
    return safe or "gateway-egress"


def _dlq_path() -> Path:
    raw = os.getenv(
        "GATEWAY_EGRESS_DLQ_PATH",
        "~/jarvis/state/gateway-resilience/gateway-egress-dlq.sqlite3",
    )
    return Path(raw).expanduser()


def _dlq_max_size() -> int:
    return _bounded_int_env(
        "GATEWAY_EGRESS_DLQ_MAX_SIZE",
        default=250,
        minimum=10,
        maximum=10_000,
    )


def _breaker_for(operation: str) -> CircuitBreaker:
    breaker = _BREAKERS.get(operation)
    if breaker is not None:
        return breaker
    breaker = CircuitBreaker(
        name=operation,
        failure_threshold=_bounded_int_env(
            "GATEWAY_EGRESS_CIRCUIT_FAILURE_THRESHOLD",
            default=3,
            minimum=1,
            maximum=20,
        ),
        window_seconds=_bounded_float_env(
            "GATEWAY_EGRESS_CIRCUIT_WINDOW_SECONDS",
            default=60.0,
            minimum=1.0,
            maximum=3600.0,
        ),
        open_seconds=_bounded_float_env(
            "GATEWAY_EGRESS_CIRCUIT_OPEN_SECONDS",
            default=300.0,
            minimum=1.0,
            maximum=3600.0,
        ),
    )
    _BREAKERS[operation] = breaker
    return breaker


def _dlq_for(operation: str) -> DeadLetterQueue:
    queue_name = _safe_queue_name(operation)
    dlq = _DLQS.get(queue_name)
    if dlq is not None:
        return dlq
    dlq = DeadLetterQueue(
        db_path=_dlq_path(),
        queue_name=queue_name,
        max_size=_dlq_max_size(),
    )
    _DLQS[queue_name] = dlq
    return dlq


def _sanitize_payload_summary(payload_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not payload_summary:
        return {}
    try:
        return json.loads(json.dumps(payload_summary, default=str))
    except Exception:
        return {"summary_repr": repr(payload_summary)}


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, CircuitOpenError):
        return "circuit_open"
    if isinstance(exc, RetryableResponseError):
        return f"http_{exc.response.status_code}"
    if isinstance(exc, HTTPException):
        return f"http_exception_{exc.status_code}"
    if isinstance(exc, httpx.RequestError):
        return "request_error"
    return exc.__class__.__name__.lower()


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, RetryableResponseError):
        return True
    if isinstance(exc, HTTPException):
        return exc.status_code in _RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.RequestError)


async def _enqueue_failure(
    *,
    operation: str,
    attempts: int,
    exc: Exception,
    payload_summary: dict[str, Any] | None,
) -> None:
    reason = _failure_reason(exc)
    payload = {
        "operation": operation,
        "attempts": attempts,
        "reason": reason,
        "error_class": exc.__class__.__name__,
        "payload_summary": _sanitize_payload_summary(payload_summary),
    }
    try:
        await _dlq_for(operation).enqueue(payload, reason=reason)
    except Exception as dlq_exc:
        logger.warning(
            "gateway_egress_dlq_enqueue_failed operation=%s error_class=%s",
            operation,
            dlq_exc.__class__.__name__,
        )


async def run_with_resilience(
    operation: str,
    execute: Callable[[], Awaitable[T]],
    *,
    payload_summary: dict[str, Any] | None = None,
    retryable: Callable[[Exception], bool] | None = None,
) -> T:
    retry_check = retryable or _is_retryable_exception
    attempts = _retry_attempts()
    breaker = _breaker_for(operation)

    for attempt in range(1, attempts + 1):
        try:
            return await breaker.call(execute)
        except CircuitOpenError as exc:
            await _enqueue_failure(
                operation=operation,
                attempts=attempt,
                exc=exc,
                payload_summary=payload_summary,
            )
            logger.warning(
                "gateway_egress_circuit_open operation=%s attempt=%d",
                operation,
                attempt,
            )
            raise
        except Exception as exc:
            should_retry = retry_check(exc)
            if should_retry and attempt < attempts:
                delay_s = _retry_delay_seconds(attempt)
                logger.warning(
                    "gateway_egress_retry operation=%s attempt=%d delay_ms=%d error_class=%s",
                    operation,
                    attempt,
                    int(delay_s * 1000),
                    exc.__class__.__name__,
                )
                await asyncio.sleep(delay_s)
                continue
            await _enqueue_failure(
                operation=operation,
                attempts=attempt,
                exc=exc,
                payload_summary=payload_summary,
            )
            logger.warning(
                "gateway_egress_failed operation=%s attempt=%d retryable=%s error_class=%s",
                operation,
                attempt,
                should_retry,
                exc.__class__.__name__,
            )
            raise

    raise RuntimeError(f"unreachable retry loop for operation={operation}")


async def request_with_resilience(
    *,
    operation: str,
    method: str,
    url: str,
    timeout: float | httpx.Timeout | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    data: Any = None,
    follow_redirects: bool = False,
    client: Any | None = None,
    client_factory: Callable[..., Any] | None = None,
    retryable_status_codes: set[int] | frozenset[int] | None = None,
    payload_summary: dict[str, Any] | None = None,
    failure_detail: str | None = None,
) -> httpx.Response:
    retryable_codes = retryable_status_codes or _RETRYABLE_STATUS_CODES
    method_name = method.lower()

    async def _send_with(active_client: Any) -> httpx.Response:
        request_kwargs: dict[str, Any] = {}
        if headers is not None:
            request_kwargs["headers"] = headers
        if params is not None:
            request_kwargs["params"] = params
        if json_body is not None:
            request_kwargs["json"] = json_body
        if data is not None:
            request_kwargs["data"] = data

        sender = getattr(active_client, method_name, None)
        if callable(sender):
            response = await sender(url, **request_kwargs)
        else:
            response = await active_client.request(
                method.upper(), url, **request_kwargs
            )
        if response.status_code in retryable_codes:
            raise RetryableResponseError(response)
        return response

    async def _execute() -> httpx.Response:
        if client is not None:
            return await _send_with(client)

        factory = client_factory or httpx.AsyncClient
        client_kwargs: dict[str, Any] = {}
        if timeout is not None:
            client_kwargs["timeout"] = timeout
        if follow_redirects:
            client_kwargs["follow_redirects"] = True
        async with factory(**client_kwargs) as active_client:
            return await _send_with(active_client)

    try:
        return await run_with_resilience(
            operation,
            _execute,
            payload_summary=payload_summary,
        )
    except RetryableResponseError as exc:
        return exc.response
    except CircuitOpenError as exc:
        detail = failure_detail or operation
        raise HTTPException(
            status_code=503,
            detail=f"{detail} circuit is open",
        ) from exc
    except httpx.RequestError as exc:
        detail = failure_detail or operation
        raise HTTPException(
            status_code=502,
            detail=f"{detail} request failed",
        ) from exc
