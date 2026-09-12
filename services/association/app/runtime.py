from contextvars import ContextVar

model_override: ContextVar[str | None] = ContextVar("association_model_override", default=None)
reasoning_override: ContextVar[str | None] = ContextVar("association_reasoning_override", default=None)
