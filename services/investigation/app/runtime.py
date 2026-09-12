from contextvars import ContextVar

model_override: ContextVar[str | None] = ContextVar("investigation_model_override", default=None)
reasoning_override: ContextVar[str | None] = ContextVar("investigation_reasoning_override", default=None)
