# 🔒 Use stable Python (CRITICAL)
FROM python:3.10-slim-bookworm

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    git \
    curl \
    libffi-dev \
    libssl-dev \
    fonts-dejavu-core \
    ffmpeg \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install rest (ONCE)
RUN pip install --no-cache-dir -r requirements.txt

# Copy main files
COPY main.py .
COPY config.py .
COPY database.py .
COPY auth.py .

# Copy source directories
COPY core/ ./core/
COPY agents/ ./agents/
COPY middleware/ ./middleware/
COPY models/ ./models/
COPY routers/ ./routers/
COPY services/ ./services/
COPY utils/ ./utils/

EXPOSE 5000
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Use --preload for memory efficiency, but models load async so app starts quickly
# Increase timeout for model loading and heavy processing
# For AKS: Use 2 workers (better for multi-core nodes)
# For Web Apps: Use 1 worker (limited resources)
# Default to 2 workers (can be overridden via env var)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "1"]
