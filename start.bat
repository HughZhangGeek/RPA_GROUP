@echo off
chdir /d "C:\Users\Administrator\PycharmProjects\RPA_GROUP"

call conda activate RPA_GROUP

start "RPA Service" cmd /k "conda activate RPA_GROUP && uvicorn RPA:app --host 0.0.0.0 --port 8000"

echo RPA Service started.
echo Queue Monitor: http://localhost:8000/queue-monitor
pause >nul