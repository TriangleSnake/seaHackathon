from contextvars import ContextVar

model_override: ContextVar[str | None] = ContextVar("detection_model_override", default=None)
reasoning_override: ContextVar[str | None] = ContextVar("detection_reasoning_override", default=None)
