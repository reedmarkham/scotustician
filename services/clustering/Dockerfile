FROM python:3.11-slim

# Install system dependencies for numerical libraries and hdbscan compilation
RUN apt-get update && apt-get install -y \
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
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir Cython numpy scipy scikit-learn && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Create non-root user for security
RUN useradd -m -u 1000 analyzer && chown -R analyzer:analyzer /app
USER analyzer

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run the analysis
CMD ["python", "main.py"]