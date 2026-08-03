FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    TTC_DAEMON_HOST=0.0.0.0 \
    TTC_DAEMON_PORT=8766 \
    TTC_DATA_DIR=/data

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

COPY ttc_daemon ./ttc_daemon

RUN mkdir -p /data

EXPOSE 8766

CMD ["python", "-m", "ttc_daemon.main"]
