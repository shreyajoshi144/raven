# Raven
> AI-powered personal safety platform for risk-aware navigation, one-tap SOS, live location sharing, and emergency assistance.

## Overview

Raven is a personal safety platform designed to help people respond quickly in unsafe situations and make smarter location decisions. It combines emergency alerts, trusted contact management, route safety, and AI-assisted guidance in one system.

<img width="680" height="460" alt="architecture" src="https://github.com/user-attachments/assets/a3fbbfcb-1902-4d45-8c5b-6cf41d26c8b4" />

## Why Raven

Most safety apps solve only one part of the problem. Raven connects prevention, response, and coordination in a single workflow:

- Detect or anticipate risk
- Trigger SOS instantly
- Share live location with trusted contacts
- Guide users toward safer routes
- Support emergency response with intelligent assistance

## Architecture

The frontend talks to a single FastAPI backend organized into three modules
(Auth, Contacts, SOS), which reads and writes to PostgreSQL, uses Redis for
caching and sessions, and calls out to Twilio and Firebase to actually notify
people during an emergency.

## Core Features

- **Smart SOS** — one-tap emergency alert with GPS capture and live location updates
- **Trusted Circle** — manage verified emergency contacts and control who receives alerts
- **Safe Navigation** — route safety scoring with map-based guidance *(roadmap)*
- **Community Intelligence** — crowd-sourced incident reporting for local awareness *(roadmap)*
- **AI Assistant** — natural-language emergency support and guidance *(roadmap)*
- **Risk Forecasting** — predictive safety analytics for proactive decision-making *(roadmap)*

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.11+, Pydantic v2 |
| Database | PostgreSQL (production), SQLite (local development) |
| ORM / Migrations | SQLAlchemy 2.0, Alembic |
| Auth | JWT (python-jose), bcrypt password hashing |
| Caching / Sessions | Redis |
| Notifications | Twilio (SMS), Firebase (push) |
| Frontend | HTML5, CSS3, vanilla JavaScript, Leaflet.js, Chart.js |
| Deployment | Docker, Docker Compose |

## Engineering Highlights

A few of the harder problems solved while building and hardening this system:

- **Enum consistency across ORM and API layers.** SQLAlchemy's `Enum` type matches by Python enum *member name* by default, while the API passes in Pydantic's string-*value* enums — a mismatch that writes silently and only fails on the next read. Traced it across the ORM/schema boundary and fixed storage and lookup to be consistent by value on both the contacts and SOS models.
- **Dependency graph triage, not whack-a-mole.** A failing `pip install` pointed at `psycopg2-binary`, but the real cause was a missing prebuilt wheel for the target Python version. Verified wheel availability directly against PyPI's index rather than guessing, and applied the same process to a `pydantic-core`/`asyncpg` build failure — landing on a Python-version pin instead of forcing a full C/Rust toolchain on every contributor's machine.
- **`passlib` × `bcrypt` version incompatibility.** A newer `bcrypt` silently breaks the unmaintained `passlib==1.7.4` via an internal API change, surfacing as a misleading "password too long" error unrelated to the actual password. Recognized it as a known ecosystem incompatibility and pinned a compatible `bcrypt` version to restore correct auth behavior.
- **Config loading that fails safe, not silently.** `pydantic-settings` tries to JSON-parse list-typed environment variables by default, so a plain comma-separated `ALLOWED_ORIGINS` in `.env` crashed the app before it could log anything. Added a validator so the same `.env` works whether origins are JSON or comma-separated.
- **Dev ergonomics kept separate from production correctness.** The repo shipped with no Alembic migrations, so a fresh clone had no way to create tables. Rather than papering over it, added an explicit, clearly-commented dev-only table-creation step, with docs flagging exactly when to switch to real migrations for production.

## Project Structure

```text
RAVENAGENT/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/   # auth, users, emergency_contacts, sos
│   │   ├── core/               # config, database, security
│   │   ├── models/             # SQLAlchemy models
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── services/           # notification / business logic
│   │   └── main.py
│   ├── alembic/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── static/{css,js,images}/
│   └── index.html
├── docs/
│   └── architecture.svg
├── docker-compose.yml
└── .env.example
```

## Getting Started

> Use **Python 3.11 or 3.12** — a few pinned dependencies (`pydantic-core`, `asyncpg`) have no prebuilt wheels for 3.13 yet.

### Option 1: Docker

```bash
git clone <repo-url>
cd RAVENAGENT
cp .env.example .env
docker-compose up -d
docker-compose exec backend alembic upgrade head
```

- API → `http://localhost:8000`
- Docs → `http://localhost:8000/docs`

### Option 2: Local development (SQLite, no Docker needed)

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env .
# point DATABASE_URL at a local SQLite file, e.g.:
# DATABASE_URL=sqlite:///./raven_dev.db
python -m uvicorn app.main:app --reload
```

Tables are created automatically on first startup in this mode — no migrations needed for local dev.

## API Endpoints

| Area | Endpoint | Purpose |
|---|---|---|
| Auth | `POST /api/v1/auth/register` | Create an account |
| Auth | `POST /api/v1/auth/login` | Log in, receive a JWT |
| Auth | `GET /api/v1/auth/me` | Get the current user |
| Contacts | `GET /POST /api/v1/emergency-contacts/` | List / add trusted contacts |
| Contacts | `POST /api/v1/emergency-contacts/{id}/verify` | Verify a contact |
| SOS | `POST /api/v1/sos/` | Trigger an SOS event with GPS location |
| SOS | `POST /api/v1/sos/{id}/location` | Push a live location update |
| SOS | `POST /api/v1/sos/{id}/notify` | Notify trusted contacts |
| User | `GET /PUT /DELETE /api/v1/users/me` | View / update / delete profile |

Full interactive documentation is auto-generated at `/docs` (Swagger) and `/redoc`.

## Environment Variables

Copy `.env.example` to `.env` and configure the values you need:

- `DATABASE_URL`, `REDIS_URL`
- `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`
- `TWILIO_*` (SMS alerts)
- `FIREBASE_*` (push notifications)
- `MAPBOX_ACCESS_TOKEN`
- `ALLOWED_ORIGINS`

None of the third-party integrations are required just to run the API and auth/SOS flows locally.

## Roadmap

- **Phase 1 (current)** — Foundation and emergency response
- **Phase 2** — Safe route engine
- **Phase 3** — Community incident reporting
- **Phase 4** — Risk prediction and AI assistant
- **Phase 5** — Analytics and enterprise features

## Privacy and Security

Raven is built with privacy-first principles:

- Passwords hashed with bcrypt, never stored in plaintext
- JWT-based auth protects user sessions
- Location sharing requires explicit consent
- Users control emergency contact visibility and verification

