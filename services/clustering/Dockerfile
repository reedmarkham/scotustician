FROM python:3.11-slim

# Install system dependencies for numerical libraries and hdbscan compilation
RUN set -ex && \
    echo "[DOCKER BUILD] Updating package lists..." && \
    apt-get update && \
    echo "[DOCKER BUILD] Installing build dependencies..." && \
    apt-get install -y \
    gcc \
    g++ \
    cmake \
    libpq-dev \
    libblas-dev \
    liblapack-dev \
    libopenblas-dev \
    gfortran \
    python3-dev \
    build-essential \
    pkg-config \
    && echo "[DOCKER BUILD] Cleaning up package cache..." && \
    rm -rf /var/lib/apt/lists/* && \
    echo "[DOCKER BUILD] System dependencies installed successfully"

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN set -ex && \
    echo "[DOCKER BUILD] Upgrading pip..." && \
    pip install --no-cache-dir --upgrade pip && \
    echo "[DOCKER BUILD] Installing core numerical libraries..." && \
    pip install --no-cache-dir Cython numpy scipy scikit-learn && \
    echo "[DOCKER BUILD] Installing requirements from requirements.txt..." && \
    pip install --no-cache-dir -r requirements.txt && \
    echo "[DOCKER BUILD] Python dependencies installed successfully"

# Copy application code
COPY *.py .
RUN echo "[DOCKER BUILD] Application code copied successfully" && ls -la *.py

# Create non-root user for security
RUN set -ex && \
    echo "[DOCKER BUILD] Creating non-root user..." && \
    useradd -m -u 1000 analyzer && \
    chown -R analyzer:analyzer /app && \
    echo "[DOCKER BUILD] User setup completed successfully"
USER analyzer

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run the analysis
CMD echo "[DOCKER RUN] Starting clustering analysis..." && python main.py