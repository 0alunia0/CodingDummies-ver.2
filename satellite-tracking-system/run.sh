#!/bin/bash

# Script to run FastAPI application - Satellite Management System

echo "🚀 Starting Satellite Orbit Tracking System.."
echo ""

# Activate virtual environment
source .venv/bin/activate

# Run server from API module
uvicorn satellite_api:system_api --reload --host 0.0.0.0 --port 8000

# Info
echo ""
echo "Server running at: http://localhost:8000"
echo "API Documentation: http://localhost:8000/docs"
echo "Alternative documentation: http://localhost:8000/redoc"

