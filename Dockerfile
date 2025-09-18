# Stage 1: Build dependencies
FROM python:3.10-slim AS builder

WORKDIR /app

# Upgrade pip and setuptools
RUN pip install --upgrade pip setuptools

# Copy and install requirements
# This layer is cached and only re-runs when requirements.txt changes
COPY ./requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Final application image
FROM python:3.10-slim

WORKDIR /app

# Copy installed packages from the builder stage
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages

# Copy the application code
COPY ./app /app/app
COPY ./VERSION /app

# Set environment variables
ENV API_KEYS='["your_api_key_1"]'
ENV ALLOWED_TOKENS='["your_token_1"]'
ENV TZ='Asia/Shanghai'

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
