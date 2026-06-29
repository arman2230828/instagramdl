# Use the official Python 3.12 image as base
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8000

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Expose port
EXPOSE $PORT

# Command to run the application (Shell form allows resolving $PORT env variable on Render)
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
