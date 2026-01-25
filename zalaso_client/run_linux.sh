#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "First time setup: Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Installing dependencies..."
    pip install -r requirements.txt
    pip install pyngrok
else
    source venv/bin/activate
    pip install pyngrok
fi

echo "Starting Zalaso Mail..."
python3 app.py