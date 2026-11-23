# LOKI backend. Build from the repository root's docker-compose.yml (profile "app").
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --timeout 60 --retries 10 -r requirements.txt

# faster-whisper (CTranslate2) finds cuBLAS/cuDNN from the pip NVIDIA wheels on this path.
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.13/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.13/site-packages/nvidia/cudnn/lib

COPY alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY config ./config
COPY eval ./eval

RUN useradd --create-home --uid 1000 loki && mkdir -p /data/uploads && chown -R loki /data /app
USER loki

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
