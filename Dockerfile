# ---- build stage ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Install libolm and build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libolm-dev \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---- runtime stage ----
FROM python:3.11-slim

WORKDIR /app

# Install only runtime libolm
RUN apt-get update && apt-get install -y --no-install-recommends \
    libolm3 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ app/
COPY scripts/ scripts/

# Data directory (will be overridden by volume mount)
RUN mkdir -p /app/data && chown -R botuser:botuser /app

USER botuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
