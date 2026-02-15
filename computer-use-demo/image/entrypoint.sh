#!/bin/bash
set -e

./start_all.sh
./novnc_startup.sh

# Start the FastAPI backend (replaces Streamlit)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/fastapi_stdout.log 2>&1 &

# Serve the combined interface on port 8080
python http_server.py > /tmp/server_logs.txt 2>&1 &

echo "✨ Computer Use Agent Backend is ready!"
echo "➡️  Open http://localhost:8080 in your browser to begin"
echo "📡  API available at http://localhost:8000"
echo "🖥️  noVNC available at http://localhost:6080"

# Keep the container running
tail -f /dev/null
