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

   Streamlit listens on **0.0.0.0** (see `.streamlit/config.toml`). Other machines on your **Tailscale** tail can use:

   - **`http://<Tailscale-IP>:8501`** — e.g. `100.x.y.z` (`tailscale ip -4` on the host)
   - **`http://<magicdns-name>:8501`** — if MagicDNS is enabled (e.g. `my-pc.tailnet-name.ts.net`)

   `run.sh` / `run.bat` print a suggested URL when the `tailscale` CLI is installed.

   **Notes**

   - MinIO stays on **localhost** on the host; only Streamlit must be reachable over Tailscale. The browser talks to Streamlit; the app talks to MinIO locally.
   - `.streamlit/config.toml` sets **`enableXsrfProtection = false`** so the UI works when you open it by hostname/IP (common Tailscale case). Use only on a trusted tail, not on a public internet bind.
   - Allow **port 8501** in the host firewall for Tailscale (or “Tailscale” interface only) if connections fail.

3. **Environment**

   Copy `.env.example` to `.env` and adjust if MinIO is not on localhost. Load vars before Streamlit if your tooling supports it, or export them in the shell.

   To disable storage integration: `export MINIO_DISABLE=true`.

## Flow

- **Home** → **New project** (client + material/stacking Excel) → **Continue to loading tool** → enter loading name, operator, container, quantities → **Result** (plot, MinIO save, PNG download).
- **Home** → **History** → filter by client / loading / operator → **Load** (view saved plot) or **Remove**.

## What gets saved (MinIO)

Per optimization run: `meta.json`, `plot.png`, optional `material.xlsx` / `stacking.xlsx` (from the uploads used when you clicked **Apply to optimizer**).
