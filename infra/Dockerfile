# Single image for the API, the worker and one-shot migrations (command differs per service).
# Stage 1 builds the React app (web/); the legacy vanilla modules in frontend/js are imported by it (graph engine, API client).
FROM node:22-alpine AS web
WORKDIR /src
COPY web/package.json web/package-lock.json web/
RUN cd web && npm ci --no-audit --no-fund
COPY web web
COPY frontend frontend
RUN cd web && npm run build

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY backend/ ./
COPY frontend/ /app/frontend/
COPY --from=web /src/web/dist /app/web-dist
ENV FRONTEND_DIR=/app/frontend WEB_DIST_DIR=/app/web-dist APP_ENV=production
RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin raven && chown -R raven:raven /app
USER raven
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
