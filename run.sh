#!/usr/bin/env bash
# Load Optimizer — venv, dependencies, MinIO (Docker), bucket init, Streamlit
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  Load optimization (Streamlit)"
echo "=========================================="

# --- Python ---
if ! command -v python3 &>/dev/null; then
  echo "❌ python3 not found. Install Python 3.10+ and retry."
  exit 1
fi

# --- Virtual environment ---
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
  echo "✓ venv created"
fi
# shellcheck source=/dev/null
source venv/bin/activate

echo "Installing / updating Python dependencies..."
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✓ requirements.txt installed"

# --- MinIO (same defaults as storage.py / init_minio.py) ---
MINIO_CONTAINER="loadopt_minio"
MINIO_DATA_DIR="${SCRIPT_DIR}/minio-data"
export MINIO_ENDPOINT="127.0.0.1:9000"
export MINIO_ACCESS_KEY="minioadmin"
export MINIO_SECRET_KEY="minioadmin"
export MINIO_SECURE="false"
export MINIO_BUCKET="load-optimization"

echo ""
echo "MinIO (project storage) — endpoint ${MINIO_ENDPOINT}, bucket ${MINIO_BUCKET}"

if command -v docker &>/dev/null; then
  # Optional: free API ports if something is blocking (same idea as reference project)
  if command -v lsof &>/dev/null; then
    for p in 9000 9001; do
      if lsof -ti ":$p" >/dev/null 2>&1; then
        echo "Port $p in use — attempting to free it (may require sudo for foreign processes)..."
        _pids=$(lsof -ti ":$p" 2>/dev/null || true)
        if [ -n "$_pids" ]; then
          echo "$_pids" | xargs kill -9 2>/dev/null || true
        fi
      fi
    done
  fi

  if docker ps -q -f "name=^${MINIO_CONTAINER}$" 2>/dev/null | grep -q .; then
    echo "✓ MinIO already running (container ${MINIO_CONTAINER})"
  elif docker ps -aq -f "name=^${MINIO_CONTAINER}$" 2>/dev/null | grep -q .; then
    echo "Starting existing MinIO container..."
    if docker start "$MINIO_CONTAINER" >/dev/null 2>&1; then
      echo "✓ MinIO started (data in ./minio-data)"
    else
      echo "Start failed; recreating container (./minio-data kept)..."
      docker rm -f "$MINIO_CONTAINER" 2>/dev/null || true
      mkdir -p "$MINIO_DATA_DIR"
      if docker run -d --name "$MINIO_CONTAINER" \
        -p 127.0.0.1:9000:9000 -p 127.0.0.1:9001:9001 \
        -e MINIO_ROOT_USER="$MINIO_ACCESS_KEY" \
        -e MINIO_ROOT_PASSWORD="$MINIO_SECRET_KEY" \
        -v "${MINIO_DATA_DIR}:/data" \
        quay.io/minio/minio server /data --console-address ":9001"; then
        echo "✓ MinIO started (persistent data in ./minio-data)"
      else
        echo "⚠ MinIO could not start. Try: docker pull quay.io/minio/minio"
      fi
    fi
  else
    mkdir -p "$MINIO_DATA_DIR"
    echo "Starting MinIO (data in ${MINIO_DATA_DIR})..."
    if docker run -d --name "$MINIO_CONTAINER" \
      -p 127.0.0.1:9000:9000 -p 127.0.0.1:9001:9001 \
      -e MINIO_ROOT_USER="$MINIO_ACCESS_KEY" \
      -e MINIO_ROOT_PASSWORD="$MINIO_SECRET_KEY" \
      -v "${MINIO_DATA_DIR}:/data" \
      quay.io/minio/minio server /data --console-address ":9001"; then
      echo "✓ MinIO started (persistent data in ./minio-data)"
    else
      echo "⚠ MinIO could not start. Try: docker pull quay.io/minio/minio"
    fi
  fi

  echo "Waiting for MinIO API (health check)..."
  _ready=0
  _i=0
  while [ "$_i" -lt 60 ]; do
    if curl -sf "http://127.0.0.1:9000/minio/health/live" >/dev/null 2>&1; then
      echo "✓ MinIO API is ready"
      _ready=1
      break
    fi
    _i=$((_i + 1))
    sleep 0.5
  done
  if [ "$_ready" != 1 ]; then
    echo "⚠ MinIO did not become ready in time — bucket init may fail; UI will still start."
  fi
else
  echo "⚠ Docker not found — start MinIO yourself or set MINIO_* to a remote server."
fi

echo ""
echo "Ensuring bucket exists..."
python init_minio.py || true

echo ""
echo "Starting Streamlit on 0.0.0.0:8501"
if command -v tailscale &>/dev/null; then
  _ts_ip="$(tailscale ip -4 2>/dev/null || true)"
  _ts_dns="$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Self',{}).get('DNSName','').rstrip('.'))" 2>/dev/null || true)"
  if [ -n "$_ts_ip" ]; then
    echo "Tailscale — open from another device: http://${_ts_ip}:8501"
    [ -n "$_ts_dns" ] && echo "           or: http://${_ts_dns}:8501"
  fi
fi
echo "=========================================="
exec streamlit run app.py --server.address 0.0.0.0
