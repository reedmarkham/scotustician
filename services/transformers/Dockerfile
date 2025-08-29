FROM python:3.11-slim

# Install system dependencies needed for PyTorch and ML libraries
RUN set -ex && \
    echo "[DOCKER BUILD] Updating package lists..." && \
    apt-get update && \
    echo "[DOCKER BUILD] Installing system dependencies..." && \
    apt-get install -y \
    build-essential \
    curl \
    && echo "[DOCKER BUILD] Cleaning up package cache..." && \
    rm -rf /var/lib/apt/lists/* && \
    echo "[DOCKER BUILD] System dependencies installed successfully"

# Create non-root user for security
RUN set -ex && \
    echo "[DOCKER BUILD] Creating non-root user..." && \
    useradd --create-home --shell /bin/bash app && \
    echo "[DOCKER BUILD] User created successfully"
WORKDIR /code
RUN echo "[DOCKER BUILD] Setting up working directory..." && \
    chown app:app /code && \
    echo "[DOCKER BUILD] Working directory configured"

# Copy requirements first for better Docker layer caching
COPY requirements.txt .
RUN echo "[DOCKER BUILD] Setting requirements.txt permissions..." && \
    chown app:app requirements.txt && \
    echo "[DOCKER BUILD] Requirements file copied successfully"

# Install Python dependencies
RUN set -ex && \
    echo "[DOCKER BUILD] Upgrading pip..." && \
    pip install --no-cache-dir --upgrade pip && \
    echo "[DOCKER BUILD] Installing Python dependencies from requirements.txt..." && \
    pip install --no-cache-dir -r requirements.txt && \
    echo "[DOCKER BUILD] Python dependencies installed successfully"

# Copy application code
COPY *.py ./
RUN echo "[DOCKER BUILD] Setting application code permissions..." && \
    chown app:app *.py && \
    echo "[DOCKER BUILD] Application code copied successfully" && \
    ls -la *.py

# Switch to non-root user
USER app

CMD echo "[DOCKER RUN] Starting transformers service..." && python main.py