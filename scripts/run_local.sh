#!/bin/sh
# Local saved-sample verification only; never use this as a public deployment.
set -eu
cd "$(dirname "$0")/.."
export UNRENDER_ENV=development
export UNRENDER_HOST=127.0.0.1
export PORT=8000
export UNRENDER_BASE_URL=http://127.0.0.1:8000
export UNRENDER_DATA_DIR="$PWD/outputs/local-runtime"
export UNRENDER_EXTRACTOR=replay
export UNRENDER_WORKER_ENABLED=true
export UNRENDER_ALLOW_REGISTRATION=true
export UNRENDER_REQUIRE_EMAIL_VERIFICATION=false
export UNRENDER_INITIAL_CREDITS=3
export UNRENDER_SEED_DEMO=true
# An operator shell may carry production destinations; local data must stay local.
export UNRENDER_BACKUP_VOLUME=''
export UNRENDER_GOOGLE_CLIENT_ID=''
export UNRENDER_GOOGLE_CLIENT_SECRET=''
export UNRENDER_SMTP_HOST=''
export UNRENDER_SMTP_USERNAME=''
export UNRENDER_SMTP_PASSWORD=''
export UNRENDER_EMAIL_FROM=''
export STRIPE_SECRET_KEY=''
export STRIPE_WEBHOOK_SECRET=''
export STRIPE_PRICE_ID=''
exec .venv/bin/unrender-serve
