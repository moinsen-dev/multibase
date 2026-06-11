#!/bin/bash
# multibase DB init script — runs inside Postgres container on first start.
# Creates one database per configured project.

set -e

# Wait for Postgres to be ready
until pg_isready -U postgres -q; do
  echo "Waiting for Postgres..."
  sleep 1
done

# Read project names from the multibase config
CONFIG_FILE=${MULTIBASE_CONFIG:-/etc/multibase/projects.txt}
if [ -f "$CONFIG_FILE" ]; then
  while IFS= read -r project; do
    if [ -n "$project" ]; then
      db_name="${project//-/_}"
      echo "Creating database: $db_name"
      psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = '$db_name'" | grep -q 1 \
        || psql -U postgres -c "CREATE DATABASE $db_name"
    fi
  done < "$CONFIG_FILE"
fi

# Extensions (same as Supabase does)
echo "Installing extensions in template1..."
psql -U postgres -d template1 -c "CREATE EXTENSION IF NOT EXISTS pgcrypto" 2>/dev/null
psql -U postgres -d template1 -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements" 2>/dev/null

echo "multibase DB init complete."
