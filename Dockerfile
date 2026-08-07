# Official Microsoft Playwright Python image — Chromium + all OS deps pre-baked in
# No need to install system packages — they're already present in this base image
FROM mcr.microsoft.com/playwright/python:v1.52.0-jammy

ENV PYTHONUNBUFFERED=1
# This is where the base image already has Chromium installed
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Copy project files
COPY . /app

# Install Python dependencies only (no system package installs needed)
RUN pip install --upgrade pip --no-cache-dir
RUN pip install -r requirements.txt --no-cache-dir

# Verify playwright can find browsers (no --with-deps since base image has them)
RUN python -m playwright install chromium

EXPOSE 8000

CMD ["uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8000"]
