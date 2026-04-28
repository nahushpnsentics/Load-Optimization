"""
MinIO (S3-compatible) persistence for runs: material/stacking Excel, plot PNG, JSON metadata.
Configure via env: MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET, MINIO_SECURE
"""
from __future__ import annotations

import io
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

_BUCKET = os.environ.get("MINIO_BUCKET", "load-optimization")
_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
_ACCESS = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
_SECRET = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
_SECURE = os.environ.get("MINIO_SECURE", "false").lower() in ("1", "true", "yes")

_MINIO_IMPORT_OK: bool | None = None


def storage_enabled() -> bool:
    return os.environ.get("MINIO_DISABLE", "").lower() not in ("1", "true", "yes")


def minio_available() -> bool:
    """True if the minio package is installed (ImportError otherwise)."""
    global _MINIO_IMPORT_OK
    if _MINIO_IMPORT_OK is not None:
        return _MINIO_IMPORT_OK
    try:
        import minio  # noqa: F401

        _MINIO_IMPORT_OK = True
    except ImportError:
        _MINIO_IMPORT_OK = False
    return _MINIO_IMPORT_OK


def storage_ready() -> bool:
    """MinIO persistence is enabled in env and the minio client library is installed."""
    return storage_enabled() and minio_available()


def _client():
    from minio import Minio

    return Minio(
        _ENDPOINT,
        access_key=_ACCESS,
        secret_key=_SECRET,
        secure=_SECURE,
    )


def ensure_bucket() -> None:
    if not storage_ready():
        return
    c = _client()
    if not c.bucket_exists(_BUCKET):
        c.make_bucket(_BUCKET)


def _meta_key(run_id: str) -> str:
    return f"runs/{run_id}/meta.json"


def _clients_key() -> str:
    return "meta/clients.json"


def list_clients() -> list[str]:
    if not storage_ready():
        return []
    try:
        ensure_bucket()
        c = _client()
        r = c.get_object(_BUCKET, _clients_key())
        data = json.loads(r.read().decode("utf-8"))
        return sorted(set(data)) if isinstance(data, list) else []
    except Exception:
        return []


def _save_clients(names: list[str]) -> None:
    c = _client()
    raw = json.dumps(sorted(set(names)), indent=2).encode("utf-8")
    c.put_object(_BUCKET, _clients_key(), io.BytesIO(raw), length=len(raw), content_type="application/json")


def register_client(name: str) -> None:
    if not storage_ready() or not (name or "").strip():
        return
    n = name.strip()
    cur = list_clients()
    if n not in cur:
        cur.append(n)
        _save_clients(cur)


def list_runs(
    client: str | None = None,
    loading_sub: str = "",
    operator_sub: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not storage_ready():
        return []
    ensure_bucket()
    c = _client()
    out: list[dict[str, Any]] = []
    loading_sub = (loading_sub or "").lower()
    operator_sub = (operator_sub or "").lower()
    client_f = (client or "").strip().lower()
    objs = c.list_objects(_BUCKET, prefix="runs/", recursive=True)
    for o in objs:
        if not o.object_name.endswith("/meta.json"):
            continue
        try:
            r = c.get_object(_BUCKET, o.object_name)
            meta = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
        if client_f and str(meta.get("client", "")).lower() != client_f:
            continue
        ln = str(meta.get("loading_name", "")).lower()
        op = str(meta.get("operator_name", "")).lower()
        if loading_sub and loading_sub not in ln:
            continue
        if operator_sub and operator_sub not in op:
            continue
        out.append(meta)
    out.sort(key=lambda m: m.get("created_iso", ""), reverse=True)
    return out[:limit]


def save_run(
    *,
    client: str,
    loading_name: str,
    operator_name: str,
    version_name: str,
    changer: str,
    container_type: str,
    quantities: dict[str, int],
    load_data: dict,
    forbidden_on: dict[str, set],
    plot_png: bytes,
    material_xlsx: bytes | None,
    stacking_xlsx: bytes | None,
) -> str | None:
    if not storage_ready():
        return None
    ensure_bucket()
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    iso = now.isoformat()
    c = _client()

    vn = (version_name or "").strip()
    ch = (changer or "").strip()
    meta = {
        "run_id": run_id,
        "client": (client or "").strip() or "unknown",
        "loading_name": loading_name or "",
        "operator_name": operator_name or "",
        "version_name": vn,
        "changer": ch,
        "version_note": f"{vn} — {ch}".strip(" —") if (vn or ch) else "",
        "container_type": container_type or "",
        "created_iso": iso,
        "quantities": {str(k): int(v) for k, v in quantities.items()},
        "load_data": {str(k): dict(v) for k, v in load_data.items()},
        "forbidden_on": {str(k): sorted(v) for k, v in forbidden_on.items()},
    }
    register_client(meta["client"])

    jraw = json.dumps(meta, indent=2, default=str).encode("utf-8")
    c.put_object(_BUCKET, _meta_key(run_id), io.BytesIO(jraw), length=len(jraw), content_type="application/json")

    if material_xlsx:
        c.put_object(
            _BUCKET,
            f"runs/{run_id}/material.xlsx",
            io.BytesIO(material_xlsx),
            length=len(material_xlsx),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if stacking_xlsx:
        c.put_object(
            _BUCKET,
            f"runs/{run_id}/stacking.xlsx",
            io.BytesIO(stacking_xlsx),
            length=len(stacking_xlsx),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    c.put_object(
        _BUCKET,
        f"runs/{run_id}/plot.png",
        io.BytesIO(plot_png),
        length=len(plot_png),
        content_type="image/png",
    )
    return run_id


def load_run(run_id: str) -> tuple[dict[str, Any], bytes | None, bytes | None, bytes | None]:
    ensure_bucket()
    c = _client()
    r = c.get_object(_BUCKET, _meta_key(run_id))
    meta = json.loads(r.read().decode("utf-8"))

    def _get(path: str) -> bytes | None:
        try:
            o = c.get_object(_BUCKET, path)
            return o.read()
        except Exception:
            return None

    mat = _get(f"runs/{run_id}/material.xlsx")
    stx = _get(f"runs/{run_id}/stacking.xlsx")
    plot = _get(f"runs/{run_id}/plot.png")
    return meta, mat, stx, plot


def save_run_multi(
    *,
    client: str,
    loading_name: str,
    operator_name: str,
    version_name: str,
    changer: str,
    container_type: str,
    backup_days: int,
    quantities: dict[str, int],
    load_data: dict,
    forbidden_on: dict[str, set],
    trucks_meta: list[dict[str, Any]],
    truck_plots_png: list[bytes],
    unplaceable: list[dict[str, Any]] | None = None,
    material_xlsx: bytes | None = None,
    stacking_xlsx: bytes | None = None,
    catalog_xlsx: bytes | None = None,
    summary_plot_png: bytes | None = None,
) -> str | None:
    """
    Save a multi-truck (full-catalog) run. Each truck plot is stored as
    `runs/{rid}/truck_{i:03d}.png`; meta carries `mode="multi"`, `trucks` list,
    `backup_days`. The run still appears in `list_runs` like a single run.
    """
    if not storage_ready():
        return None
    ensure_bucket()
    run_id = str(uuid.uuid4())
    iso = datetime.now(timezone.utc).isoformat()
    c = _client()

    vn = (version_name or "").strip()
    ch = (changer or "").strip()
    meta = {
        "run_id": run_id,
        "mode": "multi",
        "client": (client or "").strip() or "unknown",
        "loading_name": loading_name or "",
        "operator_name": operator_name or "",
        "version_name": vn,
        "changer": ch,
        "version_note": f"{vn} — {ch}".strip(" —") if (vn or ch) else "",
        "container_type": container_type or "",
        "created_iso": iso,
        "backup_days": int(backup_days),
        "quantities": {str(k): int(v) for k, v in quantities.items()},
        "load_data": {str(k): dict(v) for k, v in load_data.items()},
        "forbidden_on": {str(k): sorted(v) for k, v in forbidden_on.items()},
        "trucks": trucks_meta,
        "unplaceable": unplaceable or [],
        "truck_count": len(trucks_meta),
    }
    register_client(meta["client"])

    jraw = json.dumps(meta, indent=2, default=str).encode("utf-8")
    c.put_object(_BUCKET, _meta_key(run_id), io.BytesIO(jraw), length=len(jraw), content_type="application/json")

    for i, png in enumerate(truck_plots_png, start=1):
        if not png:
            continue
        c.put_object(
            _BUCKET,
            f"runs/{run_id}/truck_{i:03d}.png",
            io.BytesIO(png),
            length=len(png),
            content_type="image/png",
        )
    if summary_plot_png:
        c.put_object(
            _BUCKET,
            f"runs/{run_id}/plot.png",
            io.BytesIO(summary_plot_png),
            length=len(summary_plot_png),
            content_type="image/png",
        )
    if material_xlsx:
        c.put_object(
            _BUCKET,
            f"runs/{run_id}/material.xlsx",
            io.BytesIO(material_xlsx),
            length=len(material_xlsx),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if stacking_xlsx:
        c.put_object(
            _BUCKET,
            f"runs/{run_id}/stacking.xlsx",
            io.BytesIO(stacking_xlsx),
            length=len(stacking_xlsx),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if catalog_xlsx:
        c.put_object(
            _BUCKET,
            f"runs/{run_id}/catalog.xlsx",
            io.BytesIO(catalog_xlsx),
            length=len(catalog_xlsx),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return run_id


def load_truck_plot(run_id: str, truck_index_1based: int) -> bytes | None:
    """Fetch one truck PNG from a multi-truck run."""
    if not storage_ready():
        return None
    try:
        c = _client()
        o = c.get_object(_BUCKET, f"runs/{run_id}/truck_{int(truck_index_1based):03d}.png")
        return o.read()
    except Exception:
        return None


def delete_run(run_id: str) -> None:
    c = _client()
    prefix = f"runs/{run_id}/"
    for o in c.list_objects(_BUCKET, prefix=prefix, recursive=True):
        c.remove_object(_BUCKET, o.object_name)


def delete_client_data(client: str) -> int:
    """Remove all runs for a client. Returns number of runs deleted."""
    if not storage_ready() or not (client or "").strip():
        return 0
    n = 0
    for meta in list_runs(client=client.strip(), limit=10000):
        delete_run(meta["run_id"])
        n += 1
    cur = [x for x in list_clients() if x.lower() != client.strip().lower()]
    _save_clients(cur)
    return n


def forbidden_from_meta(fbd: dict) -> dict[str, set]:
    return {k: set(v) for k, v in fbd.items()}
