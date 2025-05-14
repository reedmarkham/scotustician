FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

# Set up Python
RUN apt-get update && apt-get install -y python3 python3-pip git && \
    ln -s /usr/bin/python3 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Install Python dependencies (including torch with CUDA)
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]