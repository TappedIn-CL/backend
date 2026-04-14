# TappedIn Backend

FastAPI backend for the TappedIn project.

## Prerequisites

- Python 3.11+
- `pip` and `venv`

## Setup

From the `backend` directory:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

If you want to manage top-level dependencies and regenerate pinned versions:

```bash
pip install pip-tools
pip-compile requirements.in --output-file requirements.txt
```

## Run in Development

From `backend`:

```bash
uvicorn app.main:app --reload
```

API runs at `http://127.0.0.1:8000`.

## API Endpoints

- `GET /` returns a health-style message:
  - Response: `{"message": "Hello, World!"}`

## CORS

The app currently allows local frontend origins:

- `http://localhost:5173`
- `http://localhost:3000`

Keep only the origins you actually use in local development.
