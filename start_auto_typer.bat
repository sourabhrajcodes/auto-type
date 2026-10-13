@echo off
rem Launch Auto Typer without a console window.
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw "%~dp0auto_typer.pyw" & exit /b 0)
where pythonw >nul 2>nul && (start "" pythonw "%~dp0auto_typer.pyw" & exit /b 0)
echo Python was not found on PATH. Install Python 3 from https://www.python.org/downloads/windows/
pause
