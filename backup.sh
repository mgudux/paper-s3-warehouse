#!/bin/bash

echo "Creating backup..."
docker compose exec -T web python app/manage.py dbbackup

if [ $? -eq 0 ]; then
    echo "Backup created successfully"
else
    echo "Backup failed"
    exit 1
fi
