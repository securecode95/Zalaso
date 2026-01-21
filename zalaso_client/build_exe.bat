@echo off
cd /d "%~dp0"
echo Building Zalaso Mail Executable...

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "ZalasoMail.spec" del "ZalasoMail.spec"

if not exist "venv" (
    python -m venv venv
)

call venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
pip install pyngrok

echo Creating EXE...
:: --windowed hides the console
:: --onefile bundles everything into a single .exe
:: --add-data includes the templates and static files (Format: source;dest)
pyinstaller --noconfirm --onefile --windowed --name "ZalasoMail" --add-data "templates;templates" --add-data "static;static" app.py

echo.
echo Build complete! 
echo You can find ZalasoMail.exe in the 'dist' folder.
pause
