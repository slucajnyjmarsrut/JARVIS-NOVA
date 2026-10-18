@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ==== JARVIS NOVA PYAGENT RC3 ====
echo Для сборки нужен Python 3.11 x64 и подключение к Интернету.
py -3.11 --version >nul 2>&1
if errorlevel 1 (
 echo Не найден Python 3.11 x64. Установите Python 3.11 на СБОРОЧНЫЙ ПК.
 pause
 exit /b 1
)
py -3.11 -m pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto failed
py -3.11 -m pip install -r requirements-windows.txt
if errorlevel 1 goto failed
py -3.11 build_models.py
if errorlevel 1 goto failed
py -3.11 -m unittest discover -s tests -v
if errorlevel 1 goto failed
py -3.11 verify_models.py
if errorlevel 1 goto failed
py -3.11 -m PyInstaller --noconfirm --clean jarvis_agent.spec
if errorlevel 1 goto failed
dist\JARVIS-NOVA-PYAGENT.exe --self-test
if errorlevel 1 goto failed
echo ГОТОВО: dist\JARVIS-NOVA-PYAGENT.exe
pause
exit /b 0
:failed
echo ОШИБКА СБОРКИ. Пришлите полный журнал, чтобы исправить причину.
pause
exit /b 1
