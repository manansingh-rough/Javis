# Alembic Database Migrations

## Setup

```bash
# Install alembic
pip install alembic

# Initialize (already done — this directory exists)
alembic init -t async migrations

# Generate a new migration
alembic revision --autogenerate -m "description of changes"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

## Environment

Migrations use the sync database URL from settings (`DATABASE_SYNC_URL`).
Make sure your `.env` file has the correct connection string before running migrations.

## Current Schema

See `nexus_cloud_backend/db/models.py` for the ORM model definitions.
Migrations are auto-generated from model changes.

## First Migration

To create the initial migration from the current models:

```bash
cd nexus_cloud_backend
alembic revision --autogenerate -m "initial_schema"
alembic upgrade head