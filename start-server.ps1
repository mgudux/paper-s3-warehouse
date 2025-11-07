#!/usr/bin/env pwsh
# RUN: powershell -ExecutionPolicy Bypass -File .\start-server.ps1
param(
    [switch]$Build
)
$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path $PSScriptRoot
Push-Location $repoRoot
try {
    Write-Host "Starting database container..."
    $composeArgs = @("up")
    if ($Build) {
        $composeArgs += "--build"
    }
    $composeArgs += "-d"
    $composeArgs += "db"
    docker compose @composeArgs
    Write-Host "Applying migrations..."
    python ./src/app/manage.py makemigrations
    python ./src/app/manage.py migrate
    Write-Host "Starting Django development server (Ctrl+C to stop)..."
    python ./src/app/manage.py runserver 0.0.0.0:8000
}
finally {
    Write-Host "Stopping database container..."
    docker compose stop db | Out-Null
    Pop-Location
}