# Taco Bell Registration Bot
An automated account registration and management tool for Taco Bell.

## How?
- Playwright stealth
- Temp email using Mail.tm API (maybe will make my own temp email service later)
- Randomized delays and typing speeds

### Option 1: [Docker](https://www.docker.com/)
```bash
docker-compose up -d --build
docker-compose exec bot python src/main.py
```

### Option 2: Local Installation
```bash
pip install -r requirements.txt
playwright install chromium --with-deps
python src/main.py
```