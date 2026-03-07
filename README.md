# Taco Bell Registration Bot
An automated account registration and management tool for Taco Bell.

## How?
- Playwright stealth and randomization
- Temp email using Mailslurp API (maybe will make my own temp email service later)
- FastAPI + slowapi for rate limiting on account dispensing

### Option 1: [Docker](https://www.docker.com/)
Use `docker compose`, not `docker-compose`! Verify that you have `docker compose` installed by using `docker compose version`
```bash
docker compose up -d --build
```

### Option 2: Source
Ideally use a virtual environment
```bash
pip install -r requirements.txt
playwright install chromium --with-deps
python src/server.py
```

## API Endpoints
The server runs on port `8000` by default, but the default port forwarded by docker is `15552`. Endpoint rate limit of 5reqs/15min. Modify CORS if you want to serve this on a different port or domain.

### `POST /dispense`
Starts the automated registration process.
- Request Body:
  ```json
  {
    "first_name": "John",
    "last_name": "Taco"
  }
  ```
- Response: Streaming NDJSON.
  - `{"status": "email_generated", "email": "..."}`: Sent immediately when the email is reserved.
  - `{"status": "success", "email": "...", "code": "...", "message": "..."}`: Sent when registration is complete.

### `POST /get_code`
Retrieves a verification code for an existing account.
- Request Body:
  ```json
  {
    "email": "user@example.com"
  }
  ```
- Responses:
  ```json
  {
    "status": "success",
    "code": "123456"
  }
  ```
