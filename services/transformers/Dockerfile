FROM python:3.11-slim

# Install system dependencies needed for PyTorch and ML libraries
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app
WORKDIR /code
RUN chown app:app /code

# Copy requirements first for better Docker layer caching
COPY requirements.txt .
RUN chown app:app requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY helpers.py processors.py main.py ./
RUN chown app:app helpers.py processors.py main.py

# Switch to non-root user
USER app

CMD ["python", "main.py"]