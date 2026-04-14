# Testimonial agent API

FastAPI + SQLite + HTTP Basic auth, with **LangGraph** and **CrewAI** calling **Grok** via the [xAI API](https://docs.x.ai/docs) (OpenAI-compatible).

## Requirements

- **Python 3.10–3.13** (CrewAI is not installable on Python 3.14 yet), or run with **Docker** (image uses Python 3.12).

## Setup

1. Copy `.env.example` to `.env` and set `XAI_API_KEY`, `BASIC_AUTH_USERNAME`, and `BASIC_AUTH_PASSWORD`.
2. `python -m venv .venv` then activate and `pip install -r requirements.txt`
3. `uvicorn app.main:app --reload`

Docker: `docker build -t testimonial-api .` then `docker run --env-file .env -p 8000:8000 testimonial-api`

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | no |
| GET | `/api/me` | Basic |
| POST | `/api/langgraph` | Basic — JSON `{"prompt":"..."}` |
| POST | `/api/crew` | Basic — JSON `{"prompt":"..."}` |
| GET | `/api/runs` | Basic — recent stored runs |
