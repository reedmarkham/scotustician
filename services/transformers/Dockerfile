FROM python:3.11-slim

WORKDIR /code

COPY requirements.txt .
COPY helpers.py .
COPY processors.py .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]