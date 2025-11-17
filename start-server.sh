#!/bin/bash
# RUN: ./start-server.sh [--build]

set -e  # Exit on error

# Parse arguments
BUILD_FLAG=""
if [ "$1" = "--build" ] || [ "$1" = "-b" ]; then
    BUILD_FLAG="--build"
fi

# Get script directory
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# Cleanup function - runs on script exit
cleanup() {
    echo "Stopping database container..."
    docker compose stop db > /dev/null 2>&1 || true
    cd - > /dev/null
}

# Register cleanup to run on exit
trap cleanup EXIT INT TERM

# Start database container
echo "Starting database container..."
docker compose up -d $BUILD_FLAG db

# Apply migrations
echo "Applying migrations..."
python ./src/app/manage.py populate_history --auto
python ./src/app/manage.py makemigrations
python ./src/app/manage.py migrate

# Start Django development server
echo "Starting Django development server (Ctrl+C to stop)..."
python ./src/app/manage.py runserver 0.0.0.0:8000
