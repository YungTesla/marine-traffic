FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies eerst voor layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Applicatie code
COPY src/ src/
COPY scripts/ scripts/

# Health check: test of AISStream.io bereikbaar is
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('stream.aisstream.io', 443), timeout=5)" || exit 1

# Non-root user voor security
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN mkdir -p /data && chown appuser:appuser /data
USER appuser

CMD ["python", "-m", "src.main"]
