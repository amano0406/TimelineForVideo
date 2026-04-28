FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        tesseract-ocr \
        tesseract-ocr-jpn \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY worker/requirements-cpu.txt /app/requirements-cpu.txt
RUN pip install --no-cache-dir -r /app/requirements-cpu.txt

COPY worker/ /app/worker/
COPY configs/ /app/config/

ENV PYTHONPATH=/app/worker/src
ENTRYPOINT ["python", "-m", "timelineforvideo_worker"]
