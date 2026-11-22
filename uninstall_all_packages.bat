@echo off
echo Uninstalling all Python packages (except pip)...
echo.

cd /d "%~dp0"

:: Export all installed packages
pip freeze > temp_packages.txt

:: Uninstall all packages
pip uninstall -y -r temp_packages.txt

:: Clean up
del temp_packages.txt

echo.
echo All packages uninstalled!
echo.
echo Now you can run Run.bat to reinstall and test speed.
pause
