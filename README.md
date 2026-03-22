# Load optimization (Streamlit)

## Run (local or over Tailscale)

1. **Optional — object storage for history & auto-save**

   ```bash
   docker compose up -d
   ```

   Console: http://localhost:9001 (user `minioadmin` / `minioadmin` by default).

2. **App**

   ```bash
   ./run.sh
   ```

   On Windows: `run.bat`

   Streamlit listens on **0.0.0.0** so other machines (e.g. Tailscale peers) can open `http://<host>:8501`.

3. **Environment**

   Copy `.env.example` to `.env` and adjust if MinIO is not on localhost. Load vars before Streamlit if your tooling supports it, or export them in the shell.

   To disable storage integration: `export MINIO_DISABLE=true`.

## Flow

- **Home** → **New project** (client + material/stacking Excel) → **Continue to loading tool** → enter loading name, operator, container, quantities → **Result** (plot, MinIO save, PNG download).
- **Home** → **History** → filter by client / loading / operator → **Load** (view saved plot) or **Remove**.

## What gets saved (MinIO)

Per optimization run: `meta.json`, `plot.png`, optional `material.xlsx` / `stacking.xlsx` (from the uploads used when you clicked **Apply to optimizer**).
