# 🐦‍⬛ Raven

**See Risk Before It Sees You.**

An AI-powered personal safety platform that predicts risk, recommends safer routes, and provides intelligent emergency assistance — starting with a fast, reliable one-tap SOS system.

![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## Table of Contents

- [Product Vision](#product-vision)
- [Current Phase](#current-phase-phase-1--foundation--emergency-response-mvp)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Overview](#api-overview)
- [Environment Variables](#environment-variables)
- [Roadmap](#roadmap)
- [Privacy & Security](#privacy--security)


---

## Product Vision

Raven is a comprehensive personal safety platform that combines:

- 🆘 **Smart Emergency Response** — one-tap SOS with live location sharing
- 🗺️ **Intelligent Navigation** — AI-powered route safety scoring
- 👥 **Community Intelligence** — crowd-sourced incident reporting
- 🤖 **AI Assistant** — natural language emergency guidance
- 📈 **Risk Forecasting** — predictive safety analytics

## Current Phase: Phase 1 — Foundation & Emergency Response (MVP)

**Objective:** build a usable safety application that people can trust from day one.

- ✅ Secure authentication (JWT)
- ✅ User profile & device management
- ✅ Trusted Circle (emergency contacts, with relation & verification)
- ✅ Smart SOS with GPS capture, live location updates, and multi-channel alerts
- ✅ REST API with full interactive documentation (Swagger/ReDoc)

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI (Python 3.11+), Pydantic v2 |
| **Database** | PostgreSQL + PostGIS (prod) / SQLite (local dev) |
| **ORM & Migrations** | SQLAlchemy 2.0, Alembic |
| **Auth** | JWT (python-jose), bcrypt password hashing |
| **Caching** | Redis |
| **Notifications** | Twilio (SMS), Firebase (push) |
| **Frontend** | HTML5, CSS3, vanilla JavaScript, Leaflet.js (maps), Chart.js |
| **Deployment** | Docker + Docker Compose |

---

## Project Structure

```
RAVENAGENT/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/   # auth, users, emergency_contacts, sos
│   │   ├── core/               # config, database, security
│   │   ├── models/             # SQLAlchemy models
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── services/           # notification / business logic
│   │   └── main.py             # app entrypoint
│   ├── alembic/                # DB migrations
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── static/{css,js,images}/
│   └── index.html
├── docker-compose.yml
├── .env.example
└── PYCHARM_SETUP.md            # detailed local-setup + troubleshooting guide
```

---

## Getting Started

> **Note on Python version:** use **Python 3.11 or 3.12**. Some pinned
> dependencies (`pydantic-core`, `asyncpg`) have no prebuilt wheels for
> Python 3.13 yet and will fail to build from source. See
> [`PYCHARM_SETUP.md`](./PYCHARM_SETUP.md) for the full troubleshooting guide
> if you hit install issues.

### Option A — Docker (matches production)

```bash
git clone <repo-url> && cd RAVENAGENT
cp .env.example .env
docker-compose up -d
docker-compose exec backend alembic upgrade head
```

- Backend API → http://localhost:8000
- Interactive docs → http://localhost:8000/docs

### Option B — Local development (SQLite, no Docker needed)

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# point at a local SQLite file instead of Postgres
cp ../.env .
sed -i.bak 's|^DATABASE_URL=.*|DATABASE_URL=sqlite:///./raven_dev.db|' .env

python -m uvicorn app.main:app --reload
```

Tables are created automatically on first startup — no migrations needed for
local SQLite dev. Then open:

- Frontend → http://localhost:8000
- Interactive API docs → http://localhost:8000/docs

For the full step-by-step PyCharm setup, common errors, and their fixes, see
[`PYCHARM_SETUP.md`](./PYCHARM_SETUP.md).

---

## API Overview

Full interactive documentation is auto-generated at `/docs` (Swagger) and
`/redoc`. Key endpoints:

| Area | Endpoint | Description |
|---|---|---|
| **Auth** | `POST /api/v1/auth/register` | Create an account |
| | `POST /api/v1/auth/login` / `login/json` | Log in, receive a JWT |
| | `GET /api/v1/auth/me` | Get the current user |
| | `POST /api/v1/auth/register-device` | Register a device for push notifications |
| **Emergency Contacts** | `GET /POST /api/v1/emergency-contacts/` | List / add trusted contacts |
| | `PUT /DELETE /api/v1/emergency-contacts/{id}` | Update / remove a contact |
| | `POST /api/v1/emergency-contacts/{id}/verify` | Verify a contact |
| **SOS** | `POST /api/v1/sos/` | Trigger an SOS event with GPS location |
| | `PUT /api/v1/sos/{id}` | Update status (active/resolved/cancelled) |
| | `POST /api/v1/sos/{id}/location` | Push a live location update |
| | `POST /api/v1/sos/{id}/notify` | Notify trusted contacts |
| **Users** | `GET /PUT /DELETE /api/v1/users/me` | Manage your own profile |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values you need:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres (prod/Docker) or SQLite (local dev) connection string |
| `REDIS_URL` | Redis connection for caching/sessions |
| `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` | Auth configuration |
| `TWILIO_*` | SMS alerts for SOS notifications |
| `FIREBASE_*` | Push notifications |
| `MAPBOX_ACCESS_TOKEN` | Map rendering on the frontend |
| `ALLOWED_ORIGINS` | Comma-separated list of allowed CORS origins |

None of the third-party integrations (Twilio, Firebase, Mapbox) are required
just to run the API and auth/SOS flows locally.

---

## Roadmap

- **Phase 1 (current)** ✅ Foundation & Emergency Response
- **Phase 2** — Intelligent Navigation (SafeRoute Engine)
- **Phase 3** — Community Intelligence (incident reporting)
- **Phase 4** — AI Intelligence (risk prediction, emergency AI assistant)
- **Phase 5** — Platform & Analytics (enterprise features)

---

## Privacy & Security

Raven is privacy-first by design:

- Passwords hashed with bcrypt, never stored in plaintext
- JWT-based authentication with configurable token expiry
- Explicit consent required before location sharing
- User control over emergency contact visibility and verification


