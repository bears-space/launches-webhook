FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATE_FILE=/data/triggered_events.json \
    DEBUG_MODE=false

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

VOLUME ["/data"]

CMD ["python", "main.py"]
