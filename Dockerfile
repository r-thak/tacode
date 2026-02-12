# Use the official Playwright Python image as a base
FROM mcr.microsoft.com/playwright/python:v1.41.2-jammy

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies using uv
# We use --system to install into the user's python environment in the container
RUN uv pip install --system --no-cache -r requirements.txt

# Ensure playwright browsers are installed
RUN playwright install firefox

COPY . .

CMD ["python", "src/main.py"]
