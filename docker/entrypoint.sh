#!/bin/bash
set -e

echo "Starting Car Dealership Voice Agent..."

# Always initialize/seed database (init_db checks if already seeded)
echo "Checking database..."
python -c "from app.database.connection import init_db; init_db()"
echo "Database ready."

# Execute main command
exec "$@"
