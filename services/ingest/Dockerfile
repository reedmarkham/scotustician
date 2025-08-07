FROM python:3.9-slim

WORKDIR /code

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy consolidated application code
COPY main.py .
COPY helpers.py .
COPY .dlt/ ./.dlt/

# Set environment variables for dlt
ENV DLT_PROJECT_DIR=/code
ENV DLT_PIPELINE_DIR=/code/.dlt

# Create directory for dlt state persistence
RUN mkdir -p /code/.dlt/pipelines

# Support both ingest and test modes
CMD ["python", "main.py"]