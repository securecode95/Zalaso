#!/bin/bash
cd "$(dirname "$0")"
echo "Building Zalaso Mail Executable..."

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller
pip install pyngrok

echo "Creating Executable..."
# Note: Linux uses ':' as separator for add-data, Windows uses ';'
pyinstaller --noconfirm --onefile --windowed --name "ZalasoMail" --add-data "templates:templates" --add-data "static:static" app.py

echo "Build complete! Check the 'dist' folder."