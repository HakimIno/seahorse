"""seahorse_ai.observability — OpenTelemetry setup and helpers.

Call `setup_telemetry()` once at process startup to configure the OTel SDK.
Then use `get_tracer()` anywhere in the codebase to obtain a Tracer.

Environment variables
---------------------
OTEL_EXPORTER_OTLP_ENDPOINT   gRPC endpoint (default: http://localhost:4317)
OTEL_SERVICE_NAME              Service name that appears in Jaeger (default: seahorse-agent)
OTEL_TRACES_SAMPLER            head-based sampler (default: parentbased_always_on)
OTEL_DISABLE_TRACES            Set to "1" to completely disable tracing (e.g. unit tests)
"""
from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "seahorse-agent")
_OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
_DISABLED = os.environ.get("OTEL_DISABLE_TRACES", "0") == "1"

# Lazy-initialised singleton tracer provider
_tracer_provider: Any = None


def setup_telemetry() -> None:
    """Initialise the global OTel TracerProvider with an OTLP gRPC exporter.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _tracer_provider  # noqa: PLW0603
    if _tracer_provider is not None:
        return
    if _DISABLED:
        logger.info("OpenTelemetry tracing disabled (OTEL_DISABLE_TRACES=1)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": _SERVICE_NAME})
        # Use a short timeout to prevent hanging if collector is missing
        exporter = OTLPSpanExporter(endpoint=_OTLP_ENDPOINT, insecure=True, timeout=2)
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer_provider = provider
        logger.info(
            "OpenTelemetry configured: service=%s endpoint=%s",
            _SERVICE_NAME,
            _OTLP_ENDPOINT,
        )
    except Exception as exc:
        # If gRPC or OTel packages fail, silence the spam
        logging.getLogger("opentelemetry").setLevel(logging.ERROR)
        logger.warning("Tracing disabled: %s", exc)
        _tracer_provider = "DISABLED"


def get_tracer(name: str = "seahorse") -> Any:
    """Return an OTel Tracer (or a no-op tracer if OTel is not set up)."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return _NoopTracer()


# ── High-level helpers ─────────────────────────────────────────────────────────

@contextmanager
def span(name: str, **attrs: Any) -> Generator[Any, None, None]:
    """Context manager that wraps a block in an OTel span with the given name.

    Attributes passed as keyword arguments are set on the span.
    If OTel is not configured, this is a transparent no-op.

    Example::

        with span("planner.run", agent_id="xyz", prompt_len=42):
            result = await planner.run(request)
    """
    tracer = get_tracer()
    try:
        from opentelemetry import trace
        # Use a more explicit span management to avoid Context mismatch during async cancel
        s = tracer.start_span(name)
        token = trace.context.attach(trace.set_span_in_context(s))
        try:
            for k, v in attrs.items():
                s.set_attribute(k, v)
            yield s
        finally:
            s.end()
            try:
                trace.context.detach(token)
            except ValueError:
                # Silently ignore token mismatch during cancellation
                pass
    except (ImportError, Exception):
        yield None


def trace_async(span_name: str | None = None, **extra_attrs: Any):
    """Decorator that wraps an *async* function in an OTel span.

    Usage::

        @trace_async("tool.web_search")
        async def web_search(query: str) -> str:
            ...
    """
    def decorator(fn):  # type: ignore[no-untyped-def]
        name = span_name or fn.__qualname__

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(name, **extra_attrs):
                return await fn(*args, **kwargs)

        return wrapper

    return decorator


# ── No-op fallback ────────────────────────────────────────────────────────────

class _NoopSpan:
    def set_attribute(self, *_: Any, **__: Any) -> None:
        pass

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *_: Any) -> None:
        pass


class _NoopTracer:
    def start_as_current_span(self, *_: Any, **__: Any) -> _NoopSpan:
        return _NoopSpan()
