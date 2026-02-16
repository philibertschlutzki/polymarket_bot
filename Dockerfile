FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# git is often useful for pip install git+...
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set PYTHONPATH to include the current directory so imports work correctly
ENV PYTHONPATH=/app

# Run the application
CMD ["python", "src/main.py"]
