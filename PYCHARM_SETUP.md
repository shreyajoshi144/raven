# Running Raven in PyCharm

This guide gets the `backend` FastAPI app running locally in PyCharm. I fixed several
bugs in the code first (see "What was broken" below) — everything here has been
tested end-to-end (register → login → add emergency contact → create/update SOS event).

## 1. Open the project

Open the `RAVENAGENT` folder as the PyCharm project root (not `backend` alone), so
`.env` and `docker-compose.yml` are visible too.

## 2. Create the virtual environment

PyCharm: **Settings/Preferences → Project → Python Interpreter → Add Interpreter →
Add Local Interpreter → Virtualenv Environment → New**, base it in `backend/.venv`,
using Python 3.11 or 3.12.

Or from a terminal:

```bash
cd backend
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

## 3. Configure the database

You have two options — pick whichever is easier for you.

### Option A — SQLite (fastest, no Docker/Postgres needed)

Edit `.env` (project root) and change:

```
DATABASE_URL=sqlite:///./raven_dev.db
```

Tables are created automatically on first app startup (see fix #5 below), so there's
nothing else to do.

### Option B — Postgres via Docker Compose (matches production)

```bash
docker-compose up -d postgres redis
```

Keep `DATABASE_URL` in `.env` as the Postgres URL that's already there. Then, from
`backend/`, with your venv active:

```bash
alembic revision --autogenerate -m "initial tables"
alembic upgrade head
```

(There were no migration files in the repo yet — see fix #5.)

## 4. Run configuration in PyCharm

Create a **Run/Debug Configuration → FastAPI/Uvicorn** (or a plain **Python**
config running module `uvicorn`):

- Script/module: `uvicorn`
- Parameters: `app.main:app --reload --host 0.0.0.0 --port 8000`
- Working directory: `backend`
- Python interpreter: the venv from step 2

Or just run from the terminal (with venv active, inside `backend/`):

```bash
uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000/docs for the interactive Swagger UI, or
http://localhost:8000 for the frontend.

---

## What was broken (fixed in this copy)

1. **Missing `email-validator` dependency.** `pydantic`'s `EmailStr` needs this
   package; it wasn't in `requirements.txt`, so the app crashed on import with
   `ImportError: email-validator is not installed`. Added `email-validator==2.2.0`.

2. **`Field(..., regex=...)` in `app/schemas/user.py`.** Pydantic v2 renamed this
   kwarg to `pattern`; `regex` now raises `PydanticUserError` at import time.
   Changed `DeviceRegistration.device_type` to use `pattern=`.

3. **Missing `Boolean` import in `app/models/sos_event.py`.** The model used
   `Boolean` for `sms_sent`/`whatsapp_sent`/`push_sent` columns but never imported
   it from `sqlalchemy`, causing `NameError: name 'Boolean' is not defined`.

4. **`ALLOWED_ORIGINS` / extra `.env` fields crashed settings loading.**
   - `ALLOWED_ORIGINS` is typed as a list, but pydantic-settings tries to
     JSON-parse list-typed env values by default; the `.env` file has a plain
     comma-separated string, which isn't valid JSON, so startup failed with
     `SettingsError: error parsing value for field "ALLOWED_ORIGINS"`. Added a
     validator that splits comma-separated strings into a list.
   - The `.env` file also has `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`
     (used by `docker-compose.yml`) which weren't declared on the `Settings`
     model, and pydantic-settings rejects unknown env vars by default
     (`extra_forbidden`). Set `extra = "ignore"` in `Settings.Config`.

5. **No database tables get created.** `backend/alembic/versions/` was empty
   (no migrations), and nothing called `Base.metadata.create_all()` either, so
   every request that touched the DB failed with `no such table: users` (or the
   Postgres equivalent). Added a `Base.metadata.create_all(bind=engine)` call on
   startup as a dev convenience. For a production deployment, generate a real
   Alembic migration instead (`alembic revision --autogenerate`) and drop this
   line, since `create_all` doesn't track schema changes the way migrations do.

6. **`passlib` + newer `bcrypt` incompatibility.** `requirements.txt` pins
   `passlib==1.7.4` (its last release, from 2020) but doesn't pin `bcrypt`, so
   pip installs a modern `bcrypt` (5.x) that changed an internal API `passlib`
   depends on. Every password hash/verify call failed with
   `ValueError: password cannot be longer than 72 bytes...` regardless of actual
   password length — this is a known, well-documented incompatibility. Pinned
   `bcrypt==4.0.1` in `requirements.txt`.

7. **Enum values stored inconsistently between API and DB.** The SQLAlchemy
   `Enum` columns (`EmergencyContact.relation`, `SOSEvent.status`) matched by the
   Python enum member's *name* (e.g. `OTHER`) by default. But the API passes in
   the Pydantic schema's string-value enum (e.g. `"other"`) directly, so a
   contact created via the API stored `"other"` in the DB, and the very next read
   of that row crashed with `LookupError: 'other' is not among the defined enum
   values`. Added `values_callable=lambda e: [x.value for x in e]` to both
   columns so storage and lookup are consistent by value.

All of the above were confirmed by actually installing dependencies fresh and
running the full register → login → add contact → create/update SOS flow.
