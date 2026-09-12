FROM python:3.12-slim

WORKDIR /app

COPY services/discovery-pipeline/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/discovery-pipeline/app ./app
COPY shared/schemas ./shared/schemas

ENV DISCOVERY_PIPELINE_SCHEMA_DIR=/app/shared/schemas

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10006"]
