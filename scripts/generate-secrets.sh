#!/usr/bin/env sh
# Prints fresh random values for the required secrets (append to .env, then fill in the rest).
set -eu
gen() { python3 -c "import secrets; print(secrets.token_urlsafe(48))"; }
for k in POSTGRES_PASSWORD APP_SECRET_KEY INTERNAL_SERVICE_SECRET N8N_WEBHOOK_SECRET N8N_ENCRYPTION_KEY; do
  echo "$k=$(gen)"
done
