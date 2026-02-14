# Taco Bell Registration Bot
An automated account registration and management tool for Taco Bell.

## How?
- Playwright stealth
- Temp email using mailslurp API (maybe will make my own temp email service later)
- FastAPI + rate limiting to allow account dispensing

### Option 1: [Docker](https://www.docker.com/)
```bash
docker-compose up -d --build
```

### Option 2: Source
```bash
pip install -r requirements.txt
playwright install chromium --with-deps
python src/server.py
```

## Tools
### Get verification code
```bash
python src/get_code.py <email_address>
```
