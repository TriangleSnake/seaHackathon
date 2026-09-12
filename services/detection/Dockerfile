FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS test
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY app ./app
COPY config ./config
COPY tests ./tests
CMD ["pytest", "-q"]

FROM base AS runtime
COPY app ./app
COPY config ./config

USER 65532:65532

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
