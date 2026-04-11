@echo off
echo.
echo  GPS Petropolis - Iniciando...
echo.
pip install flask requests -q
echo.
echo  Abrindo em http://localhost:5000
echo  Pressione CTRL+C para encerrar.
echo.
python server.py
pause
