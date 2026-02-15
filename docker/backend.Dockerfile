FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY skills ./skills
COPY uvicorn_log_config.yaml ./uvicorn_log_config.yaml

EXPOSE 7777

CMD ["uvicorn", "backend.api.web_app:app", "--host", "0.0.0.0", "--port", "7777", "--log-level", "info", "--log-config", "uvicorn_log_config.yaml"]
