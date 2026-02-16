#!/bin/bash
set -e

echo "🚀 Starting Local Simulation (Paper Trading Mode)..."

# Ensure .env exists
if [ ! -f .env ]; then
    echo "⚠️ .env file not found! Please create one from .env.example"
    exit 1
fi

echo "Building and starting containers..."
docker-compose -f docker-compose.local.yml up --build
