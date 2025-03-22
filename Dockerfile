FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY src/ /app/src/
COPY k8s/ /app/k8s/

# Create directories for data
RUN mkdir -p /app/data/raw /app/data/processed 

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1


# Expose port for the REST API
EXPOSE 8080

