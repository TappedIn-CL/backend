# TappedIn Backend

FastAPI backend for TappedIn.

## Prerequisites

- Python 3.11+
- PostgreSQL running locally
- `pip` and `venv`

## 1) Create and activate a virtual environment

From the `backend` directory:

```bash
python3 -m venv venv
source venv/bin/activate
```

## 2) Install dependencies

```bash
pip install -r requirements.txt
```

Top-level dependencies are tracked in `requirements.in`.
If you add/remove a package, regenerate `requirements.txt`:

```bash
pip install pip-tools
pip-compile requirements.in --output-file requirements.txt
```

## 3) Set up PostgreSQL database

Create the database:

```bash
psql postgres
CREATE DATABASE tappedin;
\q
```

Create/update `backend/.env`:

```env
DATABASE_URL=postgresql://localhost:5432/tappedin
```

If your local Postgres requires credentials, use:

```env
DATABASE_URL=postgresql://<username>:<password>@localhost:5432/tappedin
```

## 4) Run Alembic migrations

This project now uses Alembic for schema migrations.

Apply all migrations to your database:

```bash
alembic upgrade head
```

Create a new migration after model changes:

```bash
alembic revision --autogenerate -m "describe your change"
```

Then apply it:

```bash
alembic upgrade head
```

Useful commands:

```bash
alembic current
alembic history
```

## 5) Run development server

```bash
uvicorn app.main:app --reload
```

API base URL: `http://127.0.0.1:8000`

## API Routes

- `GET /` - basic service status message
- `POST /users` - create a user
  - request body:
    ```json
    {
      "email": "alice@example.com",
      "username": "alice",
      "password": "secret123"
    }
    ```

## FastAPI Built-In Routes

- `GET /docs` - Swagger UI
- `GET /redoc` - ReDoc
- `GET /openapi.json` - OpenAPI schema

## CORS

Allowed local frontend origins:

- `http://localhost:5173`
- `http://localhost:3000`

## Troubleshooting

- `sqlalchemy.exc.ArgumentError: Expected string or URL object, got None`
  - `DATABASE_URL` is missing or `.env` is empty.
- Connection refused to Postgres
  - Ensure PostgreSQL is running and `tappedin` database exists.
- Alembic migration command fails with import/path errors
  - Run commands from the `backend` directory and confirm `DATABASE_URL` is set in `.env`.
