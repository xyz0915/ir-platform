FROM python:3.13-slim

WORKDIR /app

# ── Install system build dependencies ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Install Python dependencies ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Copy application code ──
COPY . .

# ── Create data directory for runtime persistence ──
RUN mkdir -p /app/data

# ── Security: run as non-root user ──
RUN groupadd -r ir && useradd -r -g ir -d /app -s /sbin/nologin ir && \
    chown -R ir:ir /app
USER ir

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
