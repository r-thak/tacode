FROM mcr.microsoft.com/playwright/python:v1.41.2-jammy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY requirements.txt .

RUN uv pip install --system --no-cache -r requirements.txt
RUN playwright install --with-deps

COPY . .

EXPOSE 8000

CMD ["python", "src/server.py"]
