#!/bin/bash

BACKUP_FILE=$1

if [ -n "$BACKUP_FILE" ]; then
    echo "Restoring from: $BACKUP_FILE"
    docker compose exec -T web python app/manage.py dbrestore --input-filename="$BACKUP_FILE"
else
    echo "Restoring from latest backup..."
    docker compose exec -T web python app/manage.py dbrestore
fi

if [ $? -eq 0 ]; then
    echo "Database restored successfully"
else
    echo "Restore failed"
    exit 1
fi
