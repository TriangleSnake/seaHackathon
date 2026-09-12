from contextvars import ContextVar

model_override: ContextVar[str | None] = ContextVar("patrol_model_override", default=None)
reasoning_override: ContextVar[str | None] = ContextVar("patrol_reasoning_override", default=None)
