@echo off
echo.
echo  GPS Petropolis - Iniciando...
echo.
pip install flask requests -q
echo.
echo  Abrindo em http://localhost:5000
echo  Pressione CTRL+C para encerrar.
echo.
start "" /b cmd /c "timeout /t 2 >nul && start http://localhost:5000"
python server.py
pause
 