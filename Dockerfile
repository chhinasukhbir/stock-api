FROM python:3.11-slim

WORKDIR /app

# System deps for pandas/yfinance build wheels (kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8000

# Cloud platforms (Render, Railway, Cloud Run, etc.) inject $PORT; default to 8000 locally.
ENV PORT=8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
