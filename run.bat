@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo   Load optimization (Streamlit)
echo ==========================================

where python >nul 2>&1
if errorlevel 1 (
  echo python not found. Install Python 3.10+ and add it to PATH.
  exit /b 1
)

if not exist "venv" (
  echo Creating virtual environment...
  python -m venv venv
  echo venv created.
)
call venv\Scripts\activate.bat

echo Installing / updating Python dependencies...
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
echo requirements.txt installed.

set "MINIO_CONTAINER=loadopt_minio"
set "MINIO_DATA_DIR=%~dp0minio-data"
set "MINIO_ENDPOINT=127.0.0.1:9000"
set "MINIO_ACCESS_KEY=minioadmin"
set "MINIO_SECRET_KEY=minioadmin"
set "MINIO_SECURE=false"
set "MINIO_BUCKET=load-optimization"

echo.
echo MinIO — endpoint %MINIO_ENDPOINT%  bucket %MINIO_BUCKET%

where docker >nul 2>&1
if errorlevel 1 (
  echo Docker not found — install Docker Desktop or set MINIO_* to your server.
  goto after_docker
)

docker ps -q -f "name=%MINIO_CONTAINER%" 2>nul | findstr /r "." >nul
if not errorlevel 1 (
  echo MinIO already running (container %MINIO_CONTAINER%^)
  goto minio_wait
)

docker ps -aq -f "name=%MINIO_CONTAINER%" 2>nul | findstr /r "." >nul
if errorlevel 1 goto minio_create

echo Starting existing MinIO container...
docker start "%MINIO_CONTAINER%" >nul 2>&1
if not errorlevel 1 (
  echo MinIO started.
  goto minio_wait
)

echo Start failed; recreating container...
docker rm -f "%MINIO_CONTAINER%" >nul 2>&1

:minio_create
if not exist "%MINIO_DATA_DIR%" mkdir "%MINIO_DATA_DIR%"
echo Starting MinIO (data in %MINIO_DATA_DIR%^)...
docker run -d --name "%MINIO_CONTAINER%" ^
  -p 127.0.0.1:9000:9000 -p 127.0.0.1:9001:9001 ^
  -e MINIO_ROOT_USER=%MINIO_ACCESS_KEY% ^
  -e MINIO_ROOT_PASSWORD=%MINIO_SECRET_KEY% ^
  -v "%MINIO_DATA_DIR%:/data" ^
  quay.io/minio/minio server /data --console-address ":9001"
if errorlevel 1 (
  echo MinIO could not start. Try: docker pull quay.io/minio/minio
) else (
  echo MinIO started.
)

:minio_wait
echo Waiting for MinIO API...
set WAITCOUNT=0
:wait_loop
curl -sf "http://127.0.0.1:9000/minio/health/live" >nul 2>&1
if not errorlevel 1 (
  echo MinIO API is ready.
  goto after_wait
)
timeout /t 1 /nobreak >nul
set /a WAITCOUNT+=1
if %WAITCOUNT% LSS 60 goto wait_loop
echo MinIO did not become ready in time — bucket init may fail; UI will still start.

:after_wait
:after_docker
echo.
echo Ensuring bucket exists...
python init_minio.py

echo.
echo Starting Streamlit on 0.0.0.0:8501
echo ==========================================
streamlit run app.py --server.address 0.0.0.0

endlocal
