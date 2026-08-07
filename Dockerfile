# Use official Playwright base image — Chromium + all OS deps pre-baked in
FROM mcr.microsoft.com/playwright/python:v1.52.0-jammy

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Copy project
COPY . /app

# Install Python deps
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Ensure chromium is installed in the expected path
RUN python -m playwright install chromium

EXPOSE 8000

CMD ["uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8000"]
