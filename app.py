from __future__ import annotations

import streamlit as st
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import random
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import base64
import io
import re
from pathlib import Path
import pandas as pd

try:
    import storage
except ImportError:
    storage = None  # type: ignore


def _stor() -> bool:
    return storage is not None and storage.storage_ready()


def _safe_filename_part(s: str, max_len: int = 40) -> str:
    s = (s or "").strip()
    if not s:
        return "client"
    t = re.sub(r"[^\w\-.]+", "_", s, flags=re.UNICODE)
    t = t.strip("._-") or "client"
    return t[:max_len]


def _meta_version_name() -> str:
    """Set on Materials → Continue; survives Result reruns (widget keys alone do not)."""
    return (st.session_state.get("meta_version_name") or "").strip()


def _meta_changer() -> str:
    return (st.session_state.get("meta_changer") or "").strip()


def _saved_run_label(m: dict) -> str:
    """Dropdown label: version · changer · date (no loading name)."""
    vn = (m.get("version_name") or "").strip() or "—"
    ch = (m.get("changer") or "").strip() or "—"
    iso = str(m.get("created_iso", "") or "")
    if "T" in iso[:19]:
        iso = iso[:19].replace("T", " ")
    elif len(iso) > 16:
        iso = iso[:16]
    return f"{vn} · {ch} · {iso}"


def _materials_source_is_excel() -> bool:
    """False when materials were loaded from MinIO restore / auto-latest (version & changer optional)."""
    return st.session_state.get("materials_source", "excel") == "excel"


def _png_bytes_to_pdf(png_bytes: bytes) -> bytes | None:
    """Wrap a PNG (e.g. from MinIO) in a single-page PDF for download."""
    if not png_bytes:
        return None
    try:
        from matplotlib import image as mpimage

        arr = mpimage.imread(io.BytesIO(png_bytes))
        h, w = arr.shape[0], arr.shape[1]
        fig, ax = plt.subplots(figsize=(max(4, w / 150), max(3, h / 150)))
        ax.imshow(arr)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="pdf", bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        return None


def _meta_client_name() -> str:
    """
    Canonical client for MinIO/history/PDF. Set on Materials → Continue.
    Widget `project_client_name` is empty on Result/Tool reruns without the text input mounted.
    """
    for key in ("meta_client_name", "project_client_name", "project_existing_client"):
        s = (st.session_state.get(key) or "").strip()
        if s:
            return s
    return ""


def _meta_container_key() -> str | None:
    """Set on Tool → Next; survives Result reruns when the container selectbox is not mounted."""
    ct = st.session_state.get("meta_container_selected")
    if ct is not None and str(ct).strip():
        return str(ct).strip()
    c2 = st.session_state.get("container_selected")
    if c2 is not None and str(c2).strip():
        return str(c2).strip()
    return None


def _pack_result_fingerprint(
    quantities: dict, container_key: str, forbidden_on: dict, load_data: dict
) -> str:
    q = json.dumps(
        sorted(
            (str(k), int(quantities.get(k, 0) or 0))
            for k in sorted(quantities, key=str)
            if int(quantities.get(k, 0) or 0) > 0
        ),
        separators=(",", ":"),
    )
    fo = json.dumps({str(k): sorted(str(x) for x in v) for k, v in sorted(forbidden_on.items())})
    ld = json.dumps(load_data, sort_keys=True, default=str)
    raw = f"{q}|{container_key}|{fo}|{ld}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


st.set_page_config(
    page_title="Load Optimizer",
    page_icon="images/sentics_logo.png",
    layout='wide'
)

st.logo("images/sentics.png",size="large")
_schn_path = Path(__file__).resolve().parent / "images" / "schnellecke.png"
if _schn_path.is_file():
    _schn_b64 = base64.b64encode(_schn_path.read_bytes()).decode()
    # Native asset is 464×109; flex centers on full page (columns alone left-align the image in the cell).
    st.markdown(
        f'<div style="display:flex;justify-content:center;width:100%;margin:0.25rem 0 0.75rem 0;">'
        f'<img src="data:image/png;base64,{_schn_b64}" alt="Schnellecke" '
        f'style="width:464px;max-width:min(92vw,464px);height:auto;display:block;" />'
        f"</div>",
        unsafe_allow_html=True,
    )
else:
    st.caption("Missing `images/schnellecke.png`.")
# Data
container = {"Mega Trailer":{"length":13600,"width":2500, "height":2700},
             "Conventional Trailer":{"length":13600,"width":2500, "height":3000}}
_DEFAULT_STAPEL_UNLIMITED = 9999

DEFAULT_LOAD = {
    "1057730": {"length": 2550, "width": 850, "height": 665, "weight": 373.134, "pallet_type": "RKN", "stapelfaktor": _DEFAULT_STAPEL_UNLIMITED},
    "1186892": {"length": 2550, "width": 850, "height": 965, "weight": 535.364, "pallet_type": "RKH", "stapelfaktor": _DEFAULT_STAPEL_UNLIMITED},
    "1279747": {"length": 3186, "width": 730, "height": 560, "weight": 387.304, "pallet_type": "EWP", "stapelfaktor": _DEFAULT_STAPEL_UNLIMITED},
    "1186893": {"length": 2570, "width": 850, "height": 965, "weight": 537.548, "pallet_type": "RKH", "stapelfaktor": _DEFAULT_STAPEL_UNLIMITED},
}

# Weight chart
chart = [
    (0, 9000),(1000, 11000),(2000, 13000),(3000, 15000),(4000, 17000),(5000, 18000),(6000, 21000),
    (7000, 28000),(8000, 28000),(8500,21000),(9000, 9000),(9500, 4000),(10000, 3000),(11000, 2000),
    (12000, 1000),(13000, 1000),(14000, 1000)
]

DEFAULT_FORBIDDEN_ON = {
    "EWP": {"RKN", "RKH"},
    "RKN": {"EWP"},
    "RKH": {"EWP"},
}


def _copy_load(d):
    return {k: dict(v) for k, v in d.items()}


def _normalize_stapelfaktor(raw) -> int:
    """
    Max number of units of the same material allowed in one vertical XY column (footprint overlap).
    Excel 0 or blank → 1 (no stacking). Missing column → large default (effectively unlimited).
    """
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return 1
    try:
        v = int(round(float(str(raw).strip().replace(",", "."))))
    except (ValueError, TypeError):
        return 1
    if v <= 0:
        return 1
    return v


def _stapelfaktor_from_box(box: dict) -> int:
    if not box or "stapelfaktor" not in box:
        return _DEFAULT_STAPEL_UNLIMITED
    return _normalize_stapelfaktor(box.get("stapelfaktor"))


def _load_data_from_saved_meta(meta: dict) -> dict:
    """Rebuild load_data from MinIO meta.json (JSON numbers may be int/float/str)."""
    raw = meta.get("load_data") or {}
    out: dict = {}
    for k, v in raw.items():
        if not isinstance(v, dict):
            continue
        try:
            sf = v.get("stapelfaktor", _DEFAULT_STAPEL_UNLIMITED)
            if sf is None or (isinstance(sf, float) and np.isnan(sf)):
                sf = _DEFAULT_STAPEL_UNLIMITED
            else:
                try:
                    sf = int(round(float(sf)))
                except (TypeError, ValueError):
                    sf = _DEFAULT_STAPEL_UNLIMITED
                if sf <= 0:
                    sf = 1
            out[str(k)] = {
                "length": float(v["length"]),
                "width": float(v["width"]),
                "height": float(v["height"]),
                "weight": float(v.get("weight", 0) or 0),
                "pallet_type": str(v.get("pallet_type", "UNK")).strip() or "UNK",
                "stapelfaktor": sf,
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _copy_forbidden(fd):
    return {k: set(v) for k, v in fd.items()}


def _norm_col_key(c) -> str:
    s = str(c).lower().replace(" ", "")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


def _norm_col_key_flat(c) -> str:
    """Letters/digits only — good for DE/EN header matching."""
    s = str(c).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", s)


# --- Excel import: pallet labels (matrix headers → codes used in load / forbidden_on) ---
_MATRIX_HEADER_TO_PALLET = {
    "RKN": "RKN",
    "RKH": "RKH",
    "Gitterbox": "GIBO",
    "Euro-Palette": "EP",
    "Einweg-Palette (EP Maße)": "EWP",
    "Einweg-Palette (HP Maße)": "EWPHP",
    "Halb-Palette": "HALB",
}


def matrix_label_to_pallet(label) -> str | None:
    if label is None or (isinstance(label, float) and np.isnan(label)):
        return None
    s = str(label).strip()
    if not s:
        return None
    if s in _MATRIX_HEADER_TO_PALLET:
        return _MATRIX_HEADER_TO_PALLET[s]
    u = s.upper()
    if u in ("RKN", "RKH", "EWP", "EP", "GIBO", "KLT", "HP"):
        return u
    flat = _norm_col_key_flat(s)
    en_flat_to_code = (
        ("europalette", "EP"),
        ("europallet", "EP"),
        ("euro-palette", "EP"),
        ("disposablepallet", "EWP"),
        ("onewaypallet", "EWP"),
        ("halfpallet", "HALB"),
        ("gitterbox", "GIBO"),
        ("wiremeshbox", "GIBO"),
        ("cagepallet", "GIBO"),
        ("meshpallet", "GIBO"),
        ("cheppallet", "EP"),
        ("blockpallet", "EP"),
    )
    for needle, code in en_flat_to_code:
        n = _norm_col_key_flat(needle)
        if len(n) >= 4 and (flat == n or n in flat or (len(flat) >= 6 and flat in n)):
            return code
    return s.split()[0].upper() if s else None


def ladungstraeger_to_pallet_type(s) -> str:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return "UNK"
    t = str(s).strip().upper()
    if not t:
        return "UNK"
    if "EWP" in t or "ONE-WAY" in t or "ONEWAY" in t or "DISPOSABLE PALLET" in t:
        return "EWP"
    if "RKN" in t:
        return "RKN"
    if "RKH" in t:
        return "RKH"
    if "HPAR" in t or "HPD" in t or re.search(r"\bHP\b", t) or "HALF PALLET" in t:
        return "HP"
    if (
        "EPAR" in t
        or "EPD" in t
        or re.search(r"\bEP\b", t)
        or "EURO" in t
        or "EURO PALLET" in t
        or "CHEP" in t
    ):
        return "EP"
    if "GIBO" in t or "GITTERBOX" in t or "WIRE MESH" in t or "CAGE" in t and "BOX" in t:
        return "GIBO"
    if "KLT" in t:
        return "KLT"
    tok = t.replace(" ", "")
    if tok:
        return tok[:12]
    return "UNK"


def normalize_materialnummer(v) -> str | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
    try:
        f = float(str(v).replace(",", "."))
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        return str(f)
    except (ValueError, TypeError):
        s = str(v).strip()
        return s if s else None


def _cell_is_allowed_mark(val) -> bool:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return False
    s = str(val).strip().upper()
    return s in ("X", "✓", "Y", "YES", "JA", "1", "OK")


def _is_carrier_b_anchor_cell(v) -> bool:
    """True for cells like 'Ladungsträger B', 'Carrier B', 'Loading unit B' (DE/EN)."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return False
    f = _norm_col_key_flat(str(v).strip())
    if not f:
        return False
    exact = {
        "ladungstraegerb",
        "carrierb",
        "loadingunitb",
        "palletb",
        "bottomcarrier",
        "lowerloadingunit",
        "unittostackon",
    }
    if f in exact:
        return True
    # e.g. "CarrierB(bottom)"
    if f.endswith("b") and ("carrier" in f or "pallet" in f or "loadingunit" in f or "ladungstraeger" in f):
        return len(f) <= 28
    return False


def parse_compatibility_sheet(df: pd.DataFrame):
    """Parse 'Ladungsträger A auf B' matrix: rows = top (A), cols = bottom (B). X = allowed."""
    hdr_row = None
    for i in range(min(30, len(df))):
        for j in range(len(df.columns)):
            v = df.iat[i, j]
            if pd.notna(v) and _is_carrier_b_anchor_cell(v):
                hdr_row = i
                break
        if hdr_row is not None:
            break
    if hdr_row is None:
        raise ValueError(
            "Could not find the bottom-row anchor (e.g. 'Ladungsträger B' / 'Carrier B' / 'Loading unit B')."
        )

    b_row = hdr_row + 1
    b_cols = []
    b_labels_raw = []
    for j in range(2, len(df.columns)):
        v = df.iat[b_row, j]
        if pd.isna(v) or str(v).strip() == "":
            continue
        b_cols.append(j)
        b_labels_raw.append(str(v).strip())

    b_codes = [matrix_label_to_pallet(x) for x in b_labels_raw]
    allowed = set()
    a_codes_seen = []
    for i in range(b_row + 1, len(df)):
        a_raw = df.iat[i, 1]
        if pd.isna(a_raw) or str(a_raw).strip() == "":
            continue
        a_code = matrix_label_to_pallet(a_raw)
        if a_code is None:
            continue
        a_codes_seen.append(a_code)
        for j, b_code in zip(b_cols, b_codes):
            if b_code is None:
                continue
            if _cell_is_allowed_mark(df.iat[i, j]):
                allowed.add((a_code, b_code))

    b_ok = [c for c in b_codes if c is not None]
    matrix_pallets = set(b_ok) | set(a_codes_seen)

    return {
        "b_codes": b_ok,
        "a_codes": a_codes_seen,
        "matrix_pallets": matrix_pallets,
        "allowed_pairs": allowed,
        "b_labels_raw": b_labels_raw,
    }


def allowed_pairs_to_forbidden_on(allowed_pairs: set, matrix_pallets: set) -> dict:
    """Among matrix pallet types only: no X → bottom ∈ forbidden_on[top]."""
    out = defaultdict(set)
    for top in matrix_pallets:
        for bottom in matrix_pallets:
            if (top, bottom) in allowed_pairs:
                continue
            out[top].add(bottom)
    return {k: v for k, v in out.items() if v}


def preview_material_df_to_load(mdf: pd.DataFrame) -> dict:
    out = {}
    for _, r in mdf.iterrows():
        mat = normalize_materialnummer(r.get("Materialnummer"))
        if not mat:
            continue
        try:
            w = float(r["Breite_mm"])
            le = float(r["Länge_mm"])
            h = float(r["Höhe_mm"])
            wgt = float(r.get("Gewicht_kg", 0) or 0)
        except (TypeError, ValueError, KeyError):
            continue
        if "Stapelfaktor" in mdf.columns:
            raw_sf = r.get("Stapelfaktor")
            if pd.isna(raw_sf):
                sf = _DEFAULT_STAPEL_UNLIMITED
            else:
                sf = _normalize_stapelfaktor(raw_sf)
        else:
            sf = _DEFAULT_STAPEL_UNLIMITED
        out[mat] = {
            "length": le,
            "width": w,
            "height": h,
            "weight": wgt,
            "pallet_type": str(r.get("pallet_type", "UNK")).strip() or "UNK",
            "stapelfaktor": sf,
        }
    return out


def recompute_import_preview_after_edit(prev: dict) -> None:
    """Refresh load; update forbidden_on when a matrix was imported and/or allowed pairs exist."""
    mdf = prev["material_df"].reset_index(drop=True)
    prev["material_df"] = mdf
    prev["load"] = preview_material_df_to_load(mdf)
    ma = prev.setdefault("matrix_allowed", set())
    use_stacking_rules = bool(prev.get("has_matrix")) or len(ma) > 0
    if use_stacking_rules:
        mp = set(mdf["pallet_type"].astype(str).str.strip())
        for a, b in ma:
            mp.add(str(a).strip())
            mp.add(str(b).strip())
        prev["matrix_pallets"] = mp
        prev["forbidden_on"] = _copy_forbidden(allowed_pairs_to_forbidden_on(ma, mp))


def _require_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Missing optional dependency 'openpyxl'. From the project folder run: "
            "`./venv/bin/pip install openpyxl` (or `pip install openpyxl` in your active venv)."
        ) from e


def _match_column_by_patterns(df: pd.DataFrame, patterns: list[str]) -> str | None:
    """First column whose flat header equals or contains a pattern (longest pattern wins)."""
    best = None
    best_len = -1
    for col in df.columns:
        fk = _norm_col_key_flat(col)
        if not fk:
            continue
        for p in patterns:
            pl = _norm_col_key_flat(p)
            if not pl:
                continue
            if fk == pl or (len(pl) >= 4 and pl in fk) or (len(fk) >= 6 and fk in pl):
                if len(pl) > best_len:
                    best_len = len(pl)
                    best = col
    return best


def read_material_table(buf, sheet_name_or_index) -> pd.DataFrame:
    _require_openpyxl()
    df = pd.read_excel(buf, sheet_name=sheet_name_or_index, header=0, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def parse_order_excel_quantities(buf, mode: str = "rows") -> dict[str, int]:
    """
    Quantities per material from order/export Excel (e.g. ZMM_BS_AUSWERT…).

    mode ``rows`` (default): each **data row** with a material counts as **one** unit for that material.
    This matches evaluations where **Bestellmenge** repeats the order total on every line — summing that
    column would over-count; the intended load count is usually the **number of rows** per material.

    mode ``sum_column``: sum a quantity column (Bestellmenge, Menge, …) per material.
    """
    _require_openpyxl()
    df = pd.read_excel(buf, header=0, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    c_mat = _match_column_by_patterns(
        df,
        [
            "materialnummer",
            "materialnumber",
            "materialno",
            "matnr",
            "material",
            "articlenumber",
            "article number",
            "partnumber",
            "sku",
        ],
    )
    if not c_mat:
        raise ValueError(
            "Could not find a material column (e.g. **Material** / **Materialnummer**). "
            f"Columns in file: {', '.join(map(str, df.columns))}"
        )

    sums: dict[str, int] = defaultdict(int)

    if mode == "rows":
        for _, r in df.iterrows():
            m = normalize_materialnummer(r.get(c_mat))
            if not m:
                continue
            sums[m] += 1
        return dict(sums)

    c_qty = _match_column_by_patterns(
        df,
        [
            "bestellmenge",
            "menge",
            "quantity",
            "qty",
            "amount",
            "orderqty",
            "order quantity",
            "stueck",
            "stück",
            "pieces",
            "count",
        ],
    )
    if not c_qty:
        raise ValueError(
            "Sum mode needs a quantity column (e.g. **Bestellmenge**). "
            f"Columns in file: {', '.join(map(str, df.columns))}"
        )
    for _, r in df.iterrows():
        m = normalize_materialnummer(r.get(c_mat))
        if not m:
            continue
        raw_q = r.get(c_qty)
        if raw_q is None or (isinstance(raw_q, float) and np.isnan(raw_q)):
            continue
        try:
            q = float(str(raw_q).strip().replace(",", ".").replace(" ", ""))
        except (ValueError, TypeError):
            continue
        if abs(q - round(q)) < 1e-9:
            qi = int(round(q))
        else:
            qi = int(q)
        if qi == 0:
            continue
        sums[m] += qi
    return dict(sums)


def build_load_and_preview(df: pd.DataFrame):
    # German + English header synonyms (flat matching)
    c_mat = _match_column_by_patterns(
        df,
        [
            "materialnummer",
            "materialnumber",
            "materialno",
            "matnr",
            "mat.no",
            "articlenumber",
            "article number",
            "partnumber",
            "part number",
            "itemnumber",
            "item number",
            "sku",
            "material id",
            "materialid",
        ],
    )
    c_lad = _match_column_by_patterns(
        df,
        [
            "ladungsträger",
            "ladungstraeger",
            "loadingunit",
            "loading unit",
            "loadcarrier",
            "load carrier",
            "handlingunit",
            "handling unit",
            "carrier",
            "pallettype",
            "pallet type",
            "unitload",
            "unit load",
        ],
    )
    c_b = _match_column_by_patterns(
        df,
        [
            "breite",
            "width",
            "breitemm",
            "widthmm",
        ],
    )
    c_l = _match_column_by_patterns(
        df,
        [
            "länge",
            "laenge",
            "lange",
            "length",
            "laengemm",
            "lengthmm",
            "depth",
            "tiefe",
        ],
    )
    c_h = _match_column_by_patterns(
        df,
        [
            "höhe",
            "hoehe",
            "height",
            "hoehemm",
            "heightmm",
        ],
    )
    c_wgt = _match_column_by_patterns(
        df,
        [
            "gesamtgewicht",
            "totalweight",
            "total weight",
            "gewicht",
            "weight",
            "weightkg",
            "mass",
            "bruttogewicht",
        ],
    )
    c_name = _match_column_by_patterns(
        df,
        [
            "kurztext",
            "shorttext",
            "short text",
            "bezeichnung",
            "description",
            "materialdescription",
            "material description",
            "designation",
            "sachbezeichnung",
            "name",
        ],
    )
    c_stapel = _match_column_by_patterns(
        df,
        [
            "stapelfaktor",
            "stapel",
            "stackfactor",
            "stack factor",
            "maxstack",
            "max stack",
            "stackingfactor",
            "stacking factor",
            "layers",
        ],
    )

    if not c_mat or not c_lad or not c_b or not c_l or not c_h:
        flat_headers = ", ".join(_norm_col_key_flat(c) for c in df.columns)
        raise ValueError(
            "Material sheet needs columns for: material number, load carrier (Ladungsträger), width, length, height. "
            f"Optional: weight, description. Found headers (normalized): {flat_headers}"
        )

    rows = []
    load_out = {}
    dup_warn = []

    for _, r in df.iterrows():
        mat = normalize_materialnummer(r.get(c_mat))
        if not mat:
            continue
        if mat in load_out:
            dup_warn.append(mat)
        lad = r.get(c_lad)
        pt = ladungstraeger_to_pallet_type(lad)
        w = float(r[c_b])
        le = float(r[c_l])
        h = float(r[c_h])
        wgt = 0.0
        if c_wgt and pd.notna(r.get(c_wgt)):
            wgt = float(r[c_wgt])
        name = ""
        if c_name and pd.notna(r.get(c_name)):
            name = str(r[c_name]).strip()

        if c_stapel:
            raw_sf = r.get(c_stapel)
            if pd.isna(raw_sf):
                sf = _DEFAULT_STAPEL_UNLIMITED
            else:
                sf = _normalize_stapelfaktor(raw_sf)
        else:
            sf = _DEFAULT_STAPEL_UNLIMITED

        load_out[mat] = {
            "length": le,
            "width": w,
            "height": h,
            "weight": wgt,
            "pallet_type": pt,
            "stapelfaktor": sf,
        }
        rows.append(
            {
                "Materialnummer": mat,
                "Name": name,
                "Breite_mm": w,
                "Länge_mm": le,
                "Höhe_mm": h,
                "Gewicht_kg": wgt,
                "Ladungsträger": "" if lad is None or (isinstance(lad, float) and np.isnan(lad)) else str(lad).strip(),
                "pallet_type": pt,
                "Stapelfaktor": sf,
            }
        )

    preview_df = pd.DataFrame(rows)
    return load_out, preview_df, dup_warn


def detect_sheet_by_text(
    xl: pd.ExcelFile, *needles: str, max_rows: int = 8, match_flat: bool = False
) -> int | None:
    """First sheet whose preview contains any needle (substring). Pass several DE/EN variants."""
    _require_openpyxl()
    flat_needles = [_norm_col_key_flat(n) for n in needles if n]
    for idx, name in enumerate(xl.sheet_names):
        raw = pd.read_excel(xl, sheet_name=name, header=None, nrows=max_rows, engine="openpyxl")
        block = raw.astype(str).values.flatten()
        for x in block:
            s = str(x)
            if not match_flat:
                if any(n in s for n in needles):
                    return idx
            else:
                fx = _norm_col_key_flat(s)
                if any(fn and fn in fx for fn in flat_needles):
                    return idx
    return None

def allowed_weight_at_x(x, chart):
    for (x1, w1), (x2, w2) in zip(chart, chart[1:]):
        if x1 <= x <= x2:
            return w1 + (w2 - w1) * (x - x1) / (x2 - x1)
    return chart[-1][1]


def compute_x_weight_bins(placements, bin_size=1000, x_max=14000):
    bs = int(bin_size)
    xm = int(np.ceil(float(x_max)))
    bins = {x: 0.0 for x in range(0, xm + bs, bs)}

    for p in placements:
        x0, x1 = p["x"], p["x_e"]
        w = p["weight"]
        L = x1 - x0
        if L <= 0:
            continue

        for b in bins:
            overlap = max(0, min(x1, b + bs) - max(x0, b))
            if overlap > 0:
                bins[b] += w * overlap / L

    return bins

def overlaps(a, b):
    return not (
        a["x_e"] <= b["x"] or b["x_e"] <= a["x"] or
        a["y_e"] <= b["y"] or b["y_e"] <= a["y"] or
        a["z_e"] <= b["z"] or b["z_e"] <= a["z"]
    )


def overlaps_xy(a, b) -> bool:
    """True if footprints overlap in X/Y (same vertical column for stacking count)."""
    return not (
        a["x_e"] <= b["x"] or b["x_e"] <= a["x"] or a["y_e"] <= b["y"] or b["y_e"] <= a["y"]
    )


def violates_stapelfaktor(candidate, placements, max_layers: int) -> bool:
    """Too many units of the same material with overlapping XY footprint."""
    if max_layers >= 9000:
        return False
    n = 1
    for p in placements:
        if p.get("item") != candidate.get("item"):
            continue
        if overlaps_xy(candidate, p):
            n += 1
    return n > max_layers


def placements_respect_stapelfaktor(placements, load_ref: dict) -> bool:
    for c in placements:
        ml = _stapelfaktor_from_box(load_ref.get(c["item"], {}))
        if ml >= 9000:
            continue
        n = sum(1 for p in placements if p["item"] == c["item"] and overlaps_xy(c, p))
        if n > ml:
            return False
    return True

def has_corner_support(candidate, placements):
    for p in placements:
        if p["z_e"] >= candidate["z"]:
            x_overlap = min(candidate["x_e"], p["x_e"]) - max(candidate["x"], p["x"])
            y_overlap = min(candidate["y_e"], p["y_e"]) - max(candidate["y"], p["y"])
            if x_overlap <= 0 or y_overlap <= 0:
                continue
            if candidate["l"] > p["l"] + 40:
                continue
            if candidate["w"] > p["w"] + 40:
                continue
            return True
    return False

def violates_forbidden(candidate, placements, forbidden_on):
    for p in placements:
        if p["z_e"] == candidate["z"]:

            x_overlap = min(candidate["x_e"], p["x_e"]) - max(candidate["x"], p["x"])
            y_overlap = min(candidate["y_e"], p["y_e"]) - max(candidate["y"], p["y"])

            if x_overlap > 0 and y_overlap > 0:

                top = candidate["pallet_type"]
                bottom = p["pallet_type"]

                if top in forbidden_on:
                    if bottom in forbidden_on[top]:
                        return True

    return False

def sort_rows_by_height(placements, container_type):
    c = container[container_type]
    ROW_HEIGHT = c["width"] / 3
    GAP = 100
    START_X = 30

    rows = {0: [], 1: [], 2: []}

    # Split into rows
    for p in placements:
        band = int(((p["y"] + p["y_e"]) / 2) // ROW_HEIGHT)
        band = min(band, 2)
        rows[band].append(p)

    result = []

    for band in rows:
        cols = {}

        for p in rows[band]:
            cols.setdefault(p["x"], []).append(p)

        ordered_cols = sorted(
            cols.values(),
            key=lambda col: -sum(i["h"] for i in col)
        )

        new_x = START_X

        for col in ordered_cols:
            col.sort(key=lambda p: p["z"]) 

            z_cursor = 0
            for p in col:
                width = p["l"]

                p["x"] = new_x
                p["x_e"] = new_x + width
                p["z"] = z_cursor
                p["z_e"] = z_cursor + p["h"]

                z_cursor += p["h"]
                result.append(p)

            new_x += width + GAP

    return result

def pack_once(container_type, items, chart, forbidden_on):
    c = container[container_type]

    free_spaces = [{
        "type": "front",
        "x": 30, "y": 30, "z": 0,
        "l": c["length"], "w": c["width"], "h": c["height"]
    }]

    placements = []

    col_height = {}
    col_cap = {0: c["height"]}

    row_height = {}
    row_cap = {0: c["height"]}

    items = sorted(items, key=lambda x: x[1]["length"])

    for name, box in items:
        
        free_spaces.sort(key=lambda s: {"front": 0, "top": 1, "right": 2}[s["type"]])

        for space in free_spaces[:]:
            col_x = space["x"]
            row_y = space["y"]

            cap_x = col_cap.get(col_x, c["height"])
            cap_y = row_cap.get(row_y, c["height"])
            cap = min(cap_x, cap_y)

            for l, w, h in [
                (box["length"], box["width"], box["height"]),
                (box["width"], box["length"], box["height"])
            ]:

                if l > space["l"] or w > space["w"] or h > space["h"]:
                    continue

                if space["z"] + h > cap:
                    continue

                new_h = space["z"] + h

                def max_allowed_height_at_x(col_x, col_height, container_height):
                    left = [h for x, h in col_height.items() if x < col_x]
                    return left[-1] if left else container_height

                def max_allowed_height_at_y(row_y, row_height, container_height):
                    left = [h for x, h in row_height.items() if x < row_y]
                    return left[-1] if left else container_height

                allowed_h = max_allowed_height_at_x(col_x, col_height, c["height"])
                if new_h > allowed_h:
                    continue

                allowed_h_y = max_allowed_height_at_y(row_y, row_height, c["height"])
                if new_h > allowed_h_y:
                    continue

                candidate = {
                    "item": name,
                    "x": space["x"], "y": space["y"], "z": space["z"],
                    "l": l, "w": w, "h": h,
                    "x_e": space["x"] + l,
                    "y_e": space["y"] + w,
                    "z_e": space["z"] + h,
                    "weight": box["weight"],
                    "pallet_type": box["pallet_type"]
                }

                if any(overlaps(candidate, p) for p in placements):
                    continue

                if violates_forbidden(candidate, placements, forbidden_on):
                    continue

                if violates_stapelfaktor(candidate, placements, _stapelfaktor_from_box(box)):
                    continue

                trial = placements + [candidate]
                max_x = max(p["x_e"] for p in trial)
                bins = compute_x_weight_bins(trial, x_max=max_x)

                if any(bins[x] > allowed_weight_at_x(x + 500, chart) for x in bins):
                    continue

                if space["type"] == "top":
                    if not has_corner_support(candidate, placements):
                        continue

                placements.append(candidate)
                free_spaces.remove(space)

                col_height[col_x] = max(col_height.get(col_x, 0), new_h)
                row_height[row_y] = max(row_height.get(row_y, 0), new_h)

                col_cap[col_x + l] = col_height[col_x]
                row_cap[row_y + w] = row_height[row_y]

                free_spaces.append({
                    "type": "top",
                    "x": space["x"],
                    "y": space["y"],
                    "z": new_h,
                    "l": space["l"], "w": space["w"],
                    "h": cap - new_h
                })

                free_spaces.append({
                    "type": "right",
                    "x": space["x"] + l + 100,
                    "y": space["y"], "z": 0,
                    "l": c["length"] - (space["x"] + l + 100),
                    "w": space["w"],
                    "h": col_height[col_x]
                })

                if space["type"] == "front" and space["w"] > w:
                    free_spaces.append({
                        "type": "front",
                        "x": space["x"],
                        "y": space["y"] + w + 30,
                        "z": space["z"],
                        "l": space["l"],
                        "w": space["w"] - w - 30,
                        "h": row_height[row_y]
                    })

                break
            else:
                continue
            break

    return placements

def pack_3d(container_type, items, chart, forbidden_on, runs=50):
    best = []
    best_score = (-1, -1)
    best_raw = []

    load_ref = {}
    for n, b in items:
        load_ref[n] = b

    for _ in range(runs):
        shuffled = items[:]
        random.shuffle(shuffled)

        placements = pack_once(container_type, shuffled, chart, forbidden_on)
        score = (len(placements), sum(p["weight"] for p in placements))

        if score > best_score:
            best = placements
            best_raw = [dict(p) for p in placements]
            best_score = score

    placed_counts = Counter(p["item"] for p in best)
    total_counts = Counter(i[0] for i in items)

    unplaced_counts = {}
    for item, total in total_counts.items():
        unplaced_counts[item] =total - placed_counts.get(item, 0)

    best_sorted = sort_rows_by_height([dict(p) for p in best], container_type)
    best_sorted.sort(key=lambda p: (p["x"], p["y"], -(p["l"] + p["w"]), -p["weight"]))
    z_at = {}
    for p in best_sorted:
        k = (p["x"], p["y"])
        p["z"] = z_at.get(k, 0)
        p["z_e"] = p["z"] + p["h"]
        z_at[k] = p["z_e"]
    if placements_respect_stapelfaktor(best_sorted, load_ref):
        best = best_sorted
    else:
        best = best_raw
    return best, unplaced_counts, placed_counts


def _legend_symbol(index: int) -> str:
    """Plot label: A–Z, then AA, AB, … (any number of distinct load keys)."""
    result = ""
    n = index + 1
    while n:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result


def cuboid_faces_from_extents(x, y, z, x_e, y_e, z_e):
    v = [
        [x,   y,   z],
        [x_e, y,   z],
        [x_e, y_e, z],
        [x,   y_e, z],
        [x,   y,   z_e],
        [x_e, y,   z_e],
        [x_e, y_e, z_e],
        [x,   y_e, z_e],
    ]
    return [
        [v[0], v[1], v[5], v[4]], 
        [v[3], v[2], v[6], v[7]],  
        [v[0], v[1], v[2], v[3]], 
        [v[4], v[5], v[6], v[7]],  
        [v[1], v[2], v[6], v[5]],  
        [v[0], v[3], v[7], v[4]],  
    ]


def render_forbidden_expander() -> None:
    with st.expander("Forbidden placement", expanded=False):
        st.caption("When optimizing, the top item’s pallet type may not rest on a lower item if listed here.")
        for forbidden_key, forbidden_value in st.session_state.forbidden_on_data.items():
            st.write(f"**{forbidden_key}**: {', '.join(sorted(forbidden_value))}")


if _stor():
    try:
        storage.ensure_bucket()
    except Exception:
        pass


# Session state
if "page" not in st.session_state:
    st.session_state.page = "home"
if st.session_state.page == "input":
    st.session_state.page = "home"
if "container_selected" not in st.session_state:
    st.session_state["container_selected"] = None
if "quantities" not in st.session_state:
    st.session_state["quantities"] = {}
if "load_data" not in st.session_state:
    st.session_state.load_data = _copy_load(DEFAULT_LOAD)
if "forbidden_on_data" not in st.session_state:
    st.session_state.forbidden_on_data = _copy_forbidden(DEFAULT_FORBIDDEN_ON)

# Main pages
if st.session_state.page == "home":
    st.markdown(
        '<h1 style="text-align: center; margin: 0 0 1rem 0;">Load optimization</h1>',
        unsafe_allow_html=True,
    )
    h1, h2 = st.columns(2)
    with h1:
        if st.button("New project", use_container_width=True, key="go_new_project"):
            st.session_state.page = "new_project"
            st.session_state.materials_source = "excel"
            st.session_state.pop("_last_auto_restore_client", None)
            st.session_state.pop("np_show_add_material", None)
            st.rerun()
    with h2:
        if st.button("History", use_container_width=True, key="go_history"):
            st.session_state.page = "history"
            st.rerun()

elif st.session_state.page == "history":
    if st.button("← Home", key="hist_back_home"):
        st.session_state.page = "home"
        st.rerun()
    st.subheader("History")
    if not _stor():
        if storage is not None and storage.storage_enabled() and not storage.minio_available():
            st.warning(
                "Install the **minio** package (e.g. `pip install minio` in your venv) to enable cloud history "
                "and auto-save. You can still export a **PDF** from the result page."
            )
    clients = storage.list_clients() if _stor() else []
    hc = st.selectbox("Client", [""] + clients, key="hist_sel_client")
    hf_load = st.text_input("Filter loading name (contains)", key="hist_filter_load")
    hf_op = st.text_input("Filter operator (contains)", key="hist_filter_op")
    if hc and st.button("Remove this client and all saved runs", key="hist_del_client"):
        n = storage.delete_client_data(hc) if _stor() else 0
        st.success(f"Removed {n} run(s) for client **{hc}**.")
        st.rerun()
    if not hc:
        runs = []
        st.info("Select a **client** above to list that client’s saved runs.")
    elif _stor():
        runs = storage.list_runs(client=hc, loading_sub=hf_load, operator_sub=hf_op)
    else:
        runs = []
    if hc and not runs:
        st.caption("No runs match for this client.")
    for meta in runs:
        rid = meta["run_id"]
        _vn = meta.get("version_name") or (meta.get("version_note") or "").split("—")[0].strip()
        _ch = meta.get("changer") or ""
        _ver_line = f" · v **{_vn}**" if _vn else ""
        _ch_line = f" · by **{_ch}**" if _ch else ""
        st.markdown(
            f"**{meta.get('created_iso', '')}** · **{meta.get('loading_name', '')}** · "
            f"operator _{meta.get('operator_name', '')}_{_ver_line}{_ch_line} · `{rid[:8]}…`"
        )
        c_a, c_b = st.columns(2)
        with c_a:
            if st.button("Load", key=f"hist_load_{rid}"):
                st.session_state.history_view_run_id = rid
                st.session_state.page = "history_detail"
                st.rerun()
        with c_b:
            if st.button("Remove", key=f"hist_rem_{rid}"):
                if _stor():
                    storage.delete_run(rid)
                st.rerun()

elif st.session_state.page == "history_detail":
    if st.button("← Home", key="hd_home"):
        st.session_state.page = "home"
        st.rerun()
    if st.button("← History", key="hd_hist"):
        st.session_state.page = "history"
        st.rerun()
    rid = st.session_state.get("history_view_run_id")
    if not rid:
        st.error("No run selected.")
    else:
        try:
            meta, _mb, _sb, plot_png = storage.load_run(rid) if _stor() else ({}, None, None, None)
        except Exception as e:
            st.error(str(e))
            meta, plot_png = {}, None
        else:
            st.subheader(
                f"**{meta.get('loading_name', '')}** · Client: **{meta.get('client', '—')}** · "
                f"Operator: **{meta.get('operator_name', '')}**"
            )
            _mvn = meta.get("version_name") or ""
            _mch = meta.get("changer") or ""
            _legacy = meta.get("version_note") or ""
            st.caption(
                f"Client: **{meta.get('client', '')}** · {meta.get('created_iso', '')}"
                + (f" · Version: **{_mvn}**" if _mvn else (f" · Note: {_legacy}" if _legacy else ""))
                + (f" · Changer: **{_mch}**" if _mch else "")
            )
            if plot_png:
                _hist_pdf = _png_bytes_to_pdf(plot_png)
                if _hist_pdf:
                    st.download_button(
                        "Download report (PDF)",
                        _hist_pdf,
                        file_name=f"{meta.get('loading_name', 'result')}_plot.pdf",
                        mime="application/pdf",
                        key="hd_dl_pdf",
                    )
                else:
                    st.caption("Could not build PDF from stored image.")
                st.image(plot_png, use_container_width=True)
            else:
                st.info("No plot image stored for this run.")

elif st.session_state.page == "new_project":
    warning = False
    if st.button("← Home", key="np_home"):
        st.session_state.page = "home"
        st.rerun()

    _dp = st.session_state.pop("_deferred_session_patch", None)
    if isinstance(_dp, dict):
        for _k, _v in _dp.get("assign", {}).items():
            st.session_state[_k] = _v
        for _k in _dp.get("pop_keys", []):
            st.session_state.pop(_k, None)

    st.subheader("New project — materials & stacking")
    _np_mode = st.radio(
        "Client type",
        options=["new", "existing"],
        format_func=lambda x: "New client" if x == "new" else "Existing client",
        horizontal=True,
        key="np_client_mode",
    )

    if _np_mode == "new":
        st.text_input("Client name (required)", key="project_client_name", placeholder="e.g. ohlf")
        _cvn, _cch = st.columns(2)
        with _cvn:
            st.text_input(
                "Version name (required)",
                key="project_version_name",
                placeholder="e.g. v2.1 / matrix Q1",
            )
        with _cch:
            st.text_input(
                "Changer (required)",
                key="project_changer",
                placeholder="Who defined this version",
            )
    else:
        _cl = storage.list_clients() if _stor() else []
        st.selectbox("Client (required)", [""] + _cl, key="project_existing_client")
        _ex_pick = (st.session_state.get("project_existing_client") or "").strip()
        if not _ex_pick:
            st.session_state.pop("_last_auto_restore_client", None)
        elif _stor():
            _lar = st.session_state.get("_last_auto_restore_client")
            if _lar != _ex_pick:
                try:
                    _aruns = storage.list_runs(client=_ex_pick, limit=1)
                    if _aruns:
                        _ameta, _amat, _astx, _ = storage.load_run(_aruns[0]["run_id"])
                        _ald = _load_data_from_saved_meta(_ameta)
                        if _ald:
                            st.session_state.load_data = _copy_load(_ald)
                            st.session_state.forbidden_on_data = storage.forbidden_from_meta(
                                _ameta.get("forbidden_on") or {}
                            )
                            st.session_state.persist_material_xlsx = _amat
                            st.session_state.persist_stacking_xlsx = _astx
                            st.session_state["quantities"] = {}
                            st.session_state.pop("import_preview", None)
                            st.session_state.pop("v_edit_mat_row", None)
                            st.session_state.pop("v_edit_stack_pair", None)
                            st.session_state.pop("_pack_result_cache", None)
                            st.session_state.pop("_result_saved_once", None)
                            st.session_state.materials_source = "minio_restore"
                            st.session_state.meta_client_name = _ex_pick
                            _avr = (_ameta.get("version_name") or "").strip()
                            _acr = (_ameta.get("changer") or "").strip()
                            if _avr:
                                st.session_state.meta_version_name = _avr
                            if _acr:
                                st.session_state.meta_changer = _acr
                except Exception:
                    pass
                st.session_state._last_auto_restore_client = _ex_pick

        st.markdown("**Saved materials** (latest auto-loaded when you pick the client)")
        if not _stor():
            st.caption("Saved history not available — use **run.sh** with storage enabled.")
        elif not _ex_pick:
            st.caption("Choose a **client** to list saved snapshots.")
        else:
            _saved = storage.list_runs(client=_ex_pick, limit=50)
            if not _saved:
                st.caption(f"No saved data for **{_ex_pick}** yet — run an optimization once.")
            else:
                _r0, _r1, _r2, _r3 = st.columns([3.2, 0.9, 0.9, 0.9])
                with _r0:
                    st.selectbox(
                        "Snapshot",
                        list(range(len(_saved))),
                        format_func=lambda i: _saved_run_label(_saved[i]),
                        key="restore_run_idx",
                        label_visibility="collapsed",
                    )
                with _r1:
                    if st.button("Remove", key="np_mat_remove", help="Clear materials (demo defaults)"):
                        st.session_state.load_data = _copy_load(DEFAULT_LOAD)
                        st.session_state.forbidden_on_data = _copy_forbidden(DEFAULT_FORBIDDEN_ON)
                        st.session_state.persist_material_xlsx = None
                        st.session_state.persist_stacking_xlsx = None
                        st.session_state["quantities"] = {}
                        st.session_state.pop("import_preview", None)
                        st.session_state.materials_source = "excel"
                        st.session_state.pop("_pack_result_cache", None)
                        st.session_state.pop("_result_saved_once", None)
                        st.session_state.np_show_add_material = False
                        st.rerun()
                with _r2:
                    _px = st.session_state.get("persist_material_xlsx")
                    if _px:
                        st.download_button(
                            "Excel",
                            _px,
                            file_name=f"{_safe_filename_part(_ex_pick)}_material.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="np_dl_mat_cur",
                        )
                    else:
                        st.caption("—")
                with _r3:
                    _idx_dl = int(st.session_state.get("restore_run_idx", 0) or 0)
                    if 0 <= _idx_dl < len(_saved):
                        try:
                            _, _mb_dl, _, _ = storage.load_run(_saved[_idx_dl]["run_id"])
                            if _mb_dl:
                                st.download_button(
                                    "Sel.",
                                    _mb_dl,
                                    file_name=f"{_safe_filename_part(_ex_pick)}_material_sel.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="np_dl_mat_sel",
                                    help="Material Excel from selected snapshot",
                                )
                            else:
                                st.caption("—")
                        except Exception:
                            st.caption("—")
                    else:
                        st.caption("—")

        _b_load, _b_add = st.columns(2)
        with _b_load:
            if st.button("Load", type="primary", key="np_load_snapshot"):
                if not _stor() or not _ex_pick:
                    st.error("Pick a **client** with saved data.")
                else:
                    _saved_l = storage.list_runs(client=_ex_pick, limit=50)
                    if not _saved_l:
                        st.error("No saved snapshots for this client.")
                    else:
                        _ix = int(st.session_state.get("restore_run_idx", 0) or 0)
                        _ix = max(0, min(_ix, len(_saved_l) - 1))
                        try:
                            _rid = _saved_l[_ix]["run_id"]
                            meta, mat_b, stx_b, _ = storage.load_run(_rid)
                            ld_rest = _load_data_from_saved_meta(meta)
                            if not ld_rest:
                                st.error("Snapshot has no material dimensions.")
                            else:
                                _clm = (meta.get("client") or _ex_pick or "").strip()
                                _vr = (meta.get("version_name") or "").strip()
                                _cr = (meta.get("changer") or "").strip()
                                st.session_state._deferred_session_patch = {
                                    "assign": {
                                        "load_data": _copy_load(ld_rest),
                                        "forbidden_on_data": storage.forbidden_from_meta(
                                            meta.get("forbidden_on") or {}
                                        ),
                                        "persist_material_xlsx": mat_b,
                                        "persist_stacking_xlsx": stx_b,
                                        "quantities": {},
                                        "materials_source": "minio_restore",
                                        "meta_client_name": _clm,
                                        "meta_version_name": _vr,
                                        "meta_changer": _cr,
                                    },
                                    "pop_keys": [
                                        "import_preview",
                                        "v_edit_mat_row",
                                        "v_edit_stack_pair",
                                        "_pack_result_cache",
                                        "_result_saved_once",
                                    ],
                                }
                                st.session_state.np_show_add_material = False
                                st.session_state._last_auto_restore_client = _ex_pick
                                st.success(f"Loaded **{len(ld_rest)}** material(s) — **Continue** when ready.")
                                st.rerun()
                        except Exception as e:
                            st.error(str(e))
        with _b_add:
            if st.button("Add material", key="np_toggle_add_material"):
                st.session_state.np_show_add_material = True
                st.session_state.materials_source = "excel"
                st.rerun()

    _show_add_panel = (_np_mode == "new") or (
        _np_mode == "existing" and st.session_state.get("np_show_add_material")
    )
    _exp_title = (
        "Add material & load conditions (Excel)"
        if _np_mode == "new"
        else "Add material (Excel) — set version & changer, then upload"
    )
    _exp_open = (
        st.session_state.get("import_expanded", False)
        if _np_mode == "new"
        else bool(st.session_state.get("np_show_add_material"))
    )

    if _show_add_panel:
        with st.expander(_exp_title, expanded=_exp_open):
            if _np_mode == "existing":
                _ev1, _ev2 = st.columns(2)
                with _ev1:
                    st.text_input(
                        "Version name (required)",
                        key="project_version_name",
                        placeholder="e.g. v2.1 / matrix Q1",
                    )
                with _ev2:
                    st.text_input(
                        "Changer (required)",
                        key="project_changer",
                        placeholder="Who defined this version",
                    )
            st.caption(
                "Upload material dimensions (Materialnummer, Ladungsträger, Breite/Länge/Höhe), optional **Stapelfaktor** "
                "(max layers in one XY column; **0** → **1**), optional stacking matrix. Keys: **Materialnummer** (digits only)."
            )
            c_u1, c_u2 = st.columns(2)
            with c_u1:
                f_mat = st.file_uploader("Material list + loading (Excel)", type=["xlsx"], key="up_material")
            with c_u2:
                f_mat2 = st.file_uploader(
                    "Load / stacking matrix (separate Excel, optional)", type=["xlsx"], key="up_matrix_only"
                )
    
            mode = st.radio(
                "Workbook layout",
                ("Single file (material + matrix on different sheets)", "Two files (material file + matrix file)"),
                horizontal=True,
                key="import_layout",
            )
    
            xl_names = []
            if f_mat is not None:
                bio = io.BytesIO(f_mat.getvalue())
                xl = pd.ExcelFile(bio, engine="openpyxl")
                xl_names = xl.sheet_names
                bio.seek(0)
    
            if mode.startswith("Single") and f_mat is not None and len(xl_names) >= 1:
                bio_d = io.BytesIO(f_mat.getvalue())
                auto_m = detect_sheet_by_text(
                    pd.ExcelFile(bio_d, engine="openpyxl"),
                    "Materialnummer",
                    "Material number",
                    "Article number",
                    "Part number",
                    "MatNR",
                )
                bio_d.seek(0)
                auto_c = detect_sheet_by_text(
                    pd.ExcelFile(bio_d, engine="openpyxl"),
                    "Ladungsträger A",
                    "Ladungsträger A auf",
                    "Carrier A",
                    "Carrier A on",
                    "Loading unit A",
                    "Loading unit A on",
                )
                st.info(
                    f"Detected: material-like sheet index **{auto_m}** (0-based), "
                    f"stacking matrix sheet index **{auto_c}** — adjust if wrong."
                )
                i1, i2 = st.columns(2)
                with i1:
                    sheet_mat = st.number_input(
                        "Material sheet index (0 = first sheet)",
                        min_value=0,
                        max_value=max(0, len(xl_names) - 1),
                        value=int(auto_m if auto_m is not None else 0),
                        key="sheet_mat_idx",
                    )
                with i2:
                    sheet_mx = st.number_input(
                        "Stacking matrix sheet index",
                        min_value=0,
                        max_value=max(0, len(xl_names) - 1),
                        value=int(auto_c if auto_c is not None else min(1, len(xl_names) - 1)),
                        key="sheet_mx_idx",
                    )
            else:
                sheet_mat = 0
                sheet_mx = 0
    
            if st.button("Read Excel", key="btn_read_excel"):
                try:
                    if f_mat is None:
                        st.error("Please upload a material Excel file.")
                    else:
                        raw_m = io.BytesIO(f_mat.getvalue())
                        if mode.startswith("Single"):
                            df_m = read_material_table(raw_m, int(sheet_mat))
                            raw_m.seek(0)
                            df_c = pd.read_excel(
                                raw_m, sheet_name=int(sheet_mx), header=None, engine="openpyxl"
                            )
                        else:
                            df_m = read_material_table(io.BytesIO(f_mat.getvalue()), 0)
                            if f_mat2 is not None:
                                df_c = pd.read_excel(
                                    io.BytesIO(f_mat2.getvalue()),
                                    sheet_name=0,
                                    header=None,
                                    engine="openpyxl",
                                )
                            else:
                                df_c = None
    
                        load_new, preview_m, dups = build_load_and_preview(df_m)
    
                        parse_info = parse_compatibility_sheet(df_c) if df_c is not None else None
                        if parse_info:
                            forb_new = _copy_forbidden(
                                allowed_pairs_to_forbidden_on(
                                    parse_info["allowed_pairs"], parse_info["matrix_pallets"]
                                )
                            )
                        else:
                            forb_new = _copy_forbidden(st.session_state.forbidden_on_data)
                            st.warning("No stacking matrix loaded — forbidden rules unchanged.")
    
                        st.session_state.pop("v_edit_mat_row", None)
                        st.session_state.pop("v_edit_stack_pair", None)
                        st.session_state.pop("mat_verify_page", None)
                        st.session_state["import_preview"] = {
                            "load": load_new,
                            "forbidden_on": forb_new,
                            "material_df": preview_m.reset_index(drop=True),
                            "matrix_allowed": parse_info["allowed_pairs"] if parse_info else set(),
                            "matrix_pallets": parse_info["matrix_pallets"] if parse_info else set(),
                            "b_labels": parse_info["b_labels_raw"] if parse_info else [],
                            "dup_materialnums": dups,
                            # True when a matrix sheet was read successfully (even if 0 X-marks)
                            "has_matrix": parse_info is not None,
                        }
                        st.session_state.import_expanded = True
                        st.session_state.materials_source = "excel"
                        st.success("Parsed — review verification below and click **Apply to optimizer**.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Read failed: {e}")
    
            prev = st.session_state.get("import_preview")
            if prev:
                st.subheader("Verification")
                if prev.get("dup_materialnums"):
                    st.warning(
                        "Duplicate Materialnummer rows (last row wins): "
                        + ", ".join(sorted(set(prev["dup_materialnums"])))
                    )
    
                _VERIFY_MAT_PAGE = 20
                mdf = prev["material_df"].reset_index(drop=True)
                if "Stapelfaktor" not in mdf.columns:
                    mdf["Stapelfaktor"] = _DEFAULT_STAPEL_UNLIMITED
                prev["material_df"] = mdf
                n_mat = len(mdf)
                st.markdown(
                    "**Materials** — edit dimensions, Ladungsträger, pallet type, **Stapelfaktor** (max layers of this "
                    "material in one XY stack; 0 in Excel → 1)."
                )
                if n_mat:
                    n_pages = max(1, (n_mat + _VERIFY_MAT_PAGE - 1) // _VERIFY_MAT_PAGE)
                    p0 = st.number_input(
                        "Material page",
                        min_value=1,
                        max_value=n_pages,
                        key="mat_verify_page",
                    )
                    start = (int(p0) - 1) * _VERIFY_MAT_PAGE
                    for pos in range(start, min(start + _VERIFY_MAT_PAGE, n_mat)):
                        row = mdf.iloc[pos]
                        c1, c2 = st.columns([10, 1])
                        with c1:
                            st.markdown(
                                f"**{row['Materialnummer']}** · {row.get('pallet_type', '')} · "
                                f"{row.get('Breite_mm', '')}×{row.get('Länge_mm', '')}×{row.get('Höhe_mm', '')} mm · "
                                f"SF **{int(row.get('Stapelfaktor', _DEFAULT_STAPEL_UNLIMITED) or _DEFAULT_STAPEL_UNLIMITED)}** · "
                                f"{row.get('Ladungsträger', '')}"
                            )
                        with c2:
                            if st.button("Edit", key=f"vme_{pos}"):
                                st.session_state.v_edit_mat_row = pos
                                st.rerun()
    
                em = st.session_state.get("v_edit_mat_row")
                if em is not None and isinstance(em, int) and 0 <= em < len(mdf):
                    r = mdf.iloc[em]
                    with st.form("verify_mat_row_form"):
                        st.markdown(f"##### Edit material row {em + 1} / {len(mdf)}")
                        fn = st.text_input("Name", value=str(r.get("Name", "") or ""))
                        fmat = st.text_input("Materialnummer", value=str(r.get("Materialnummer", "") or ""))
                        fbreite = st.number_input("Breite (mm)", value=float(r["Breite_mm"]), step=1.0)
                        flaenge = st.number_input("Länge (mm)", value=float(r["Länge_mm"]), step=1.0)
                        fhoehe = st.number_input("Höhe (mm)", value=float(r["Höhe_mm"]), step=1.0)
                        fgew = st.number_input("Gewicht (kg)", value=float(r.get("Gewicht_kg", 0) or 0), step=0.01)
                        flad = st.text_input("Ladungsträger", value=str(r.get("Ladungsträger", "") or ""))
                        fpt = st.text_input("pallet_type", value=str(r.get("pallet_type", "") or ""))
                        fstapel = st.number_input(
                            "Stapelfaktor (max layers, same material, same XY footprint)",
                            min_value=1,
                            max_value=9999,
                            value=int(min(9999, max(1, int(r.get("Stapelfaktor", _DEFAULT_STAPEL_UNLIMITED) or 1)))),
                            step=1,
                            help="Use 9999 for no practical limit (same as missing column in Excel).",
                        )
                        sc, cx = st.columns(2)
                        with sc:
                            save_m = st.form_submit_button("Save row")
                        with cx:
                            cancel_m = st.form_submit_button("Cancel")
                    if cancel_m:
                        st.session_state.v_edit_mat_row = None
                        st.rerun()
                    elif save_m:
                        mdf.at[em, "Name"] = fn.strip()
                        mdf.at[em, "Materialnummer"] = fmat.strip()
                        mdf.at[em, "Breite_mm"] = fbreite
                        mdf.at[em, "Länge_mm"] = flaenge
                        mdf.at[em, "Höhe_mm"] = fhoehe
                        mdf.at[em, "Gewicht_kg"] = fgew
                        mdf.at[em, "Ladungsträger"] = flad.strip()
                        mdf.at[em, "pallet_type"] = fpt.strip() or "UNK"
                        mdf.at[em, "Stapelfaktor"] = int(fstapel)
                        prev["material_df"] = mdf
                        recompute_import_preview_after_edit(prev)
                        st.session_state.v_edit_mat_row = None
                        st.rerun()
    
                prev.setdefault("matrix_allowed", set())
                st.divider()
                st.markdown("**Stacking matrix (allowed pairs)** — top (A) on bottom (B); **Edit** per row or add pairs below.")
                if not prev.get("has_matrix") and len(prev["matrix_allowed"]) == 0:
                    st.info(
                        "No stacking sheet was imported. Use **Single file** and set the **matrix sheet index**, "
                        "or **Two files** and upload the matrix workbook. You can still **add allowed pairs** manually."
                    )
                ap_sorted = sorted(prev["matrix_allowed"])
                if not ap_sorted:
                    st.caption("_No allowed pairs yet — import a matrix or use “Add allowed pair”._")
                for i, (ta, tb) in enumerate(ap_sorted):
                    c1, c2, c3 = st.columns([4, 4, 1])
                    with c1:
                        st.markdown(str(ta))
                    with c2:
                        st.markdown(str(tb))
                    with c3:
                        if st.button("Edit", key=f"vse_{i}"):
                            st.session_state.v_edit_stack_pair = (ta, tb)
                            st.rerun()
    
                sp = st.session_state.get("v_edit_stack_pair")
                if sp is not None and sp in prev["matrix_allowed"]:
                    oa, ob = sp
                    with st.form("verify_stack_pair_form"):
                        st.markdown("##### Edit stacking pair")
                        st.caption(f"Original: **{oa}** on **{ob}**")
                        nt = st.text_input("Top (A)", value=oa)
                        nb = st.text_input("Bottom (B)", value=ob)
                        s1, s2, s3 = st.columns(3)
                        with s1:
                            save_s = st.form_submit_button("Save pair")
                        with s2:
                            del_s = st.form_submit_button("Delete pair")
                        with s3:
                            cancel_s = st.form_submit_button("Cancel")
                    if cancel_s:
                        st.session_state.v_edit_stack_pair = None
                        st.rerun()
                    elif del_s:
                        s = set(prev["matrix_allowed"])
                        s.discard(sp)
                        prev["matrix_allowed"] = s
                        recompute_import_preview_after_edit(prev)
                        st.session_state.v_edit_stack_pair = None
                        st.rerun()
                    elif save_s:
                        s = set(prev["matrix_allowed"])
                        s.discard(sp)
                        s.add((nt.strip(), nb.strip()))
                        prev["matrix_allowed"] = s
                        recompute_import_preview_after_edit(prev)
                        st.session_state.v_edit_stack_pair = None
                        st.rerun()
    
                with st.form("verify_stack_add_form"):
                    st.markdown("##### Add allowed pair")
                    at = st.text_input("Top (A) — new", key="vstack_new_a")
                    ab = st.text_input("Bottom (B) — new", key="vstack_new_b")
                    add_s = st.form_submit_button("Add pair")
                if add_s:
                    a_new = (at or "").strip()
                    b_new = (ab or "").strip()
                    if a_new and b_new:
                        s = set(prev["matrix_allowed"])
                        s.add((a_new, b_new))
                        prev["matrix_allowed"] = s
                        recompute_import_preview_after_edit(prev)
                        st.rerun()
    
                if prev.get("has_matrix") or len(prev["matrix_allowed"]) > 0:
                    mp = prev.get("matrix_pallets") or set()
                    mat_pts = set(mdf["pallet_type"].astype(str).str.strip()) if len(mdf) else set()
                    uncovered = sorted(mat_pts - mp)
                    if uncovered:
                        st.warning(
                            "These **pallet_type** values appear on materials but not in the matrix pallet set — "
                            "add pairs above if they should stack: " + ", ".join(uncovered)
                        )
    
                if st.button("Apply to optimizer", key="btn_apply_import"):
                    if f_mat is not None:
                        st.session_state.persist_material_xlsx = f_mat.getvalue()
                    if f_mat2 is not None:
                        st.session_state.persist_stacking_xlsx = f_mat2.getvalue()
                    elif mode.startswith("Single") and f_mat is not None:
                        st.session_state.persist_stacking_xlsx = f_mat.getvalue()
                    else:
                        st.session_state.persist_stacking_xlsx = None
                    recompute_import_preview_after_edit(prev)
                    st.session_state.load_data = _copy_load(prev["load"])
                    st.session_state.forbidden_on_data = _copy_forbidden(prev["forbidden_on"])
                    st.session_state.quantities.clear()
                    st.session_state.pop("import_preview", None)
                    st.session_state.pop("v_edit_mat_row", None)
                    st.session_state.pop("v_edit_stack_pair", None)
                    st.session_state.import_expanded = False
                    st.session_state.materials_source = "excel"
                    _ex_ap = (st.session_state.get("project_existing_client") or "").strip()
                    if _ex_ap:
                        st.session_state._last_auto_restore_client = _ex_ap
                    st.success("Applied. Quantities were cleared — re-select amounts for the new Materialnummer keys.")
                    st.rerun()

    render_forbidden_expander()
    if st.button("Continue to loading tool", type="primary", key="np_to_tool"):
        _cm = st.session_state.get("np_client_mode", "new")
        if _cm == "new":
            cn = (st.session_state.get("project_client_name") or "").strip()
        else:
            cn = (st.session_state.get("project_existing_client") or "").strip()
        if not cn:
            cn = (st.session_state.get("meta_client_name") or "").strip()
        vn = (st.session_state.get("project_version_name") or "").strip()
        ch = (st.session_state.get("project_changer") or "").strip()
        _need_vc = (_cm == "new") or _materials_source_is_excel()
        if not cn:
            st.error("Add a **client name** (new) or pick an **existing client**.")
        elif _need_vc and not vn:
            st.error("**Version name** is required (new client, or Excel materials).")
        elif _need_vc and not ch:
            st.error("**Changer** is required (new client, or Excel materials).")
        else:
            st.session_state.meta_client_name = cn.strip()
            if vn:
                st.session_state.meta_version_name = vn.strip()
            if ch:
                st.session_state.meta_changer = ch.strip()
            st.session_state.page = "tool"
            st.rerun()

elif st.session_state.page == "tool":
    warning = False
    if st.button("← Home", key="tool_home"):
        st.session_state.page = "home"
        st.rerun()
    if st.button("← Materials setup", key="tool_back_np"):
        st.session_state.page = "new_project"
        st.rerun()
    st.subheader("Tool — container, loading, operator, quantities")
    if _meta_version_name() or _meta_changer():
        st.caption(
            f"Version **{_meta_version_name() or '—'}** · Changer **{_meta_changer() or '—'}**"
            + (" (from saved run)" if not _materials_source_is_excel() else " (from materials form)")
        )
    st.text_input("Loading name", key="loading_run_name", placeholder="e.g. Tour / batch ID")
    st.text_input("Operator name", key="operator_name", placeholder="Operator")
    render_forbidden_expander()

    st.session_state.setdefault("quantities", {})
    ld_keys = [k for k in st.session_state.load_data.keys()]
    ld_set = set(ld_keys)

    selected = None
    qty = 0

    c_left, c_right = st.columns(2)
    with c_left:
        container_key = [k for k in container.keys()]
        st.selectbox(
            "**Select Container**",
            container_key,
            index=None,
            placeholder="Select a container",
            key="container_selected",
        )

    with c_right:
        st.markdown("**Select item key**")
        item_entry = st.radio(
            "Item source",
            options=["manual", "excel"],
            format_func=lambda x: (
                "Manual entry (pick material + quantity)"
                if x == "manual"
                else "Excel file (e.g. ZMM_BS_AUSWERT_V2_CLS_AUTOLOAD…)"
            ),
            horizontal=True,
            key="item_entry_mode",
            label_visibility="collapsed",
        )
        if item_entry == "manual":
            selected = st.selectbox(
                "Material key",
                ld_keys,
                index=None,
                placeholder="Select an item",
                key="manual_item_select",
            )
            if selected is not None:
                current_value = int(st.session_state["quantities"].get(selected, 0))
                qty = st.number_input(
                    f"Quantity for **{selected}**",
                    min_value=0,
                    step=1,
                    value=current_value,
                )
        else:
            st.caption(
                "Typical file: **ZMM_BS_AUSWERT_V2_CLS_AUTOLOAD_02_02_2026.XLSX** — each row is one schedule/delivery line. "
                "By default, **quantity = number of rows** per material (the **Bestellmenge** column often repeats the order total and must not be summed for this export)."
            )
            order_qty_mode = st.radio(
                "How to derive quantity per material",
                options=["rows", "sum"],
                format_func=lambda x: (
                    "Count rows per material (recommended for ZMM export)"
                    if x == "rows"
                    else "Sum quantity column (Bestellmenge, Menge, …)"
                ),
                key="order_qty_parse_mode",
                horizontal=True,
            )
            f_order = st.file_uploader("Order / evaluation Excel (.xlsx)", type=["xlsx"], key="order_qty_xlsx")
            if st.button("Load quantities from Excel", key="btn_load_order_qty"):
                if f_order is None:
                    st.error("Please choose an Excel file first.")
                else:
                    try:
                        sums = parse_order_excel_quantities(
                            io.BytesIO(f_order.getvalue()),
                            mode="rows" if order_qty_mode == "rows" else "sum_column",
                        )
                        applied = {k: v for k, v in sums.items() if k in ld_set}
                        unknown = sorted(set(sums.keys()) - ld_set)
                        st.session_state["quantities"] = applied
                        if unknown:
                            st.warning(
                                "Skipped material numbers that are not in the current load list: "
                                + ", ".join(unknown[:40])
                                + (" …" if len(unknown) > 40 else "")
                            )
                        st.success(f"Loaded quantities for **{len(applied)}** material(s).")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

    c1, c2 = st.columns(2)
    with c1:
        if st.session_state.get("item_entry_mode", "manual") == "manual":
            if selected is not None and qty > 0:
                st.session_state["quantities"][selected] = qty
            elif selected in st.session_state["quantities"]:
                del st.session_state["quantities"][selected]
        st.markdown("###### Saved Quantities")
        st.write(f'Container : {st.session_state["container_selected"]} ')
        for k, v in st.session_state["quantities"].items():
            st.write(f"- {k} : {v}")
    with c2:
        c1_main,c2_main,_,_=st.columns([2,3,1,3])
        with c1_main:
            if st.button("Next", key="nav_next"):
                ld_chk = st.session_state.load_data
                bad_keys = [k for k in st.session_state["quantities"] if k not in ld_chk]
                if not st.session_state["quantities"] and st.session_state["container_selected"] is None:
                    warning = True
                    msg = "both"
                elif not st.session_state["quantities"]:
                    warning = True
                    msg = "items"
                elif st.session_state["container_selected"] is None:
                    warning = True
                    msg = "container"
                elif bad_keys:
                    warning = True
                    msg = "unknown_mat"
                elif _materials_source_is_excel() and (
                    not _meta_version_name() or not _meta_changer()
                ):
                    warning = True
                    msg = "version_meta"
                else:
                    st.session_state.meta_container_selected = st.session_state["container_selected"]
                    st.session_state.pop("_result_saved_once", None)
                    st.session_state.pop("_pack_result_cache", None)
                    st.session_state.page = "result"
                    st.rerun()
        with c2_main:
            if st.button("Clear", key="c_clear"):
                st.session_state["quantities"].clear()
                st.session_state.pop("container_selected", None)
                st.session_state.pop("meta_container_selected", None)
                st.session_state.pop("_pack_result_cache", None)
                st.rerun()
                warning = False 
                st.rerun()

    warning_msg = {
        "items": "Please add items to the container to optimize...",
        "container": "Please select container to optimize...",
        "both": "Please select container and add items to optimize...",
        "unknown_mat": "Saved quantities include material numbers that are not in the load list. "
        "Use Material Excel import or remove those keys.",
        "version_meta": "**Version** and **changer** are required for **Excel** materials — set them on **Materials setup** (←), then **Continue**.",
    }
    if warning:
        st.warning(warning_msg.get(msg))

# Page: optimization result
elif st.session_state.page == "result":
    st.subheader("Result")
    if _materials_source_is_excel() and (not _meta_version_name() or not _meta_changer()):
        st.error(
            "**Version** and **changer** are required for Excel-based materials — open **← Materials setup** and set both, then **Continue**."
        )
        st.stop()
    st.caption(
        f"**Loading:** {st.session_state.get('loading_run_name') or '—'} · "
        f"**Operator:** {st.session_state.get('operator_name') or '—'} · "
        f"**Client:** {_meta_client_name() or '—'} · "
        f"**Version:** {_meta_version_name() or '—'} · "
        f"**Changer:** {_meta_changer() or '—'}"
    )
    b1, b2 = st.columns(2)
    with b1:
        if st.button("← Back to tool", key="res_tool"):
            st.session_state.pop("_pack_result_cache", None)
            st.session_state.page = "tool"
            st.rerun()
    with b2:
        if st.button("← Home", key="res_home"):
            st.session_state.pop("_pack_result_cache", None)
            st.session_state.page = "home"
            st.rerun()

    _ct = _meta_container_key()
    if not _ct or _ct not in container:
        st.error(
            "No **container** is stored for this result — use **← Back to tool**, choose a **container**, then **Next** again."
        )
        st.stop()

    items = []
    ld = st.session_state.load_data
    fo = st.session_state.forbidden_on_data
    for k, q in st.session_state["quantities"].items():
        if k not in ld:
            st.error(f"Unknown material **{k}** in quantities — go back and fix the load list or quantities.")
            st.stop()
        qi = max(0, int(q))
        for _ in range(qi):
            items.append((k, ld[k]))
    selected_keys = [
        k
        for k in st.session_state["quantities"]
        if int(st.session_state["quantities"].get(k, 0) or 0) > 0 and k in ld
    ]
    _fp = _pack_result_fingerprint(st.session_state["quantities"], _ct, fo, ld)
    _cache = st.session_state.get("_pack_result_cache")
    _use_cache = isinstance(_cache, dict) and _cache.get("fp") == _fp

    if _use_cache:
        placements = _cache["placements"]
        un = _cache["un"]
        assigned_items = Counter(_cache["assigned_items"])
        weight = _cache["weight"]
        volume = _cache["volume"]
        remaining_volume = _cache["remaining_volume"]
        denote = _cache["denote"]
        plot_png = _cache["plot_png"]
        plot_pdf = _cache.get("plot_pdf") or b""
        st.session_state._last_plot_export_ts = _cache.get("export_ts")
        st.session_state._last_plot_client_slug = _cache.get("client_slug")
        st.session_state._last_plot_png = plot_png
        st.session_state._last_plot_pdf = plot_pdf
        st.image(plot_png, use_container_width=True)
    else:
        with st.spinner("Finding the best result and plotting it..."):
            placements, un, assigned_items = pack_3d(_ct, items, chart, fo)
            weight = sum([p["weight"] for p in placements])
            volume = (sum(p["l"] * p["w"] * p["h"] for p in placements)) / 1e9
            remaining_volume = (
                container[_ct]["length"] * container[_ct]["width"] * container[_ct]["height"]
            ) / 1e9 - volume
            denote = {key: _legend_symbol(N) for N, key in enumerate(selected_keys)}

            x_max = container[_ct]["length"]
            y_max = container[_ct]["width"]
            z_max = container[_ct]["height"]

        NUM_ROWS = 3
        ROW_HEIGHT = y_max / NUM_ROWS
        bands = {0: [], 1: [], 2: []}

        for p in placements:
            y_center = (p["y"] + p["y_e"]) / 2
            band_index = int(y_center // ROW_HEIGHT)
            band_index = min(band_index, NUM_ROWS - 1)
            bands[band_index].append(p)

        band_counts = {k: len(v) for k, v in bands.items()}
        existing_bands = [k for k, v in band_counts.items() if v > 0]

        band_metrics = {}

        for band, items in bands.items():
            if not items:
                band_metrics[band] = (0, 0, 0)
            else:
                total_weight = sum(p["weight"] for p in items)
                max_x = max(p["x_e"] for p in items)
                total_height = sum(p["h"] for p in items)

                band_metrics[band] = (total_weight, max_x, total_height)
                
        sorted_bands = sorted(
            band_metrics.items(),
            key=lambda x: (-x[1][0], -x[1][1], -x[1][2])
        )

        band_remap = {}
        for new_row_index, (original_band, _) in enumerate(sorted_bands):
            band_remap[original_band] = new_row_index

        for b in bands.keys():
            if b not in band_remap:
                band_remap[b] = len(band_remap)

        band_new_y_start = {}
        for original_band in range(NUM_ROWS):
            new_row_index = band_remap[original_band]
            band_new_y_start[original_band] = new_row_index * ROW_HEIGHT

        views = {
            "3D Overview": "all",
            "Row 1": 0,
            "Row 2": 1,
            "Row 3": 2,
            "Top View": "all",
        }

        row_colors = {
            0: "blue",
            1: "red",
            2: "green"
        }

        view_angles = {
            "3D Overview": (30, 110),
            "Row 1": (0, 90),
            "Row 2": (0, 90),
            "Row 3": (0, 90),
            "Top View": (90, 90),
        }

        fig = plt.figure(figsize=(20, 12))
        _ln = (st.session_state.get("loading_run_name") or "").strip()
        _on = (st.session_state.get("operator_name") or "").strip()
        _cn = _meta_client_name()
        _vn = _meta_version_name()
        _vch = _meta_changer()
        fig.suptitle(
            f"Loading: {_ln or '—'}  |  Operator: {_on or '—'}  |  Client: {_cn or '—'}  |  "
            f"Version: {_vn or '—'}  |  Changer: {_vch or '—'}",
            fontsize=11,
            y=0.995,
        )

        for i, title in enumerate(views.keys(), 1):
            ax = fig.add_subplot(3, 4, i, projection="3d")

            for p in placements:

                y_center = (p["y"] + p["y_e"]) / 2
                original_band = int(y_center // ROW_HEIGHT)
                original_band = min(original_band, NUM_ROWS - 1)

                new_row_index = band_remap[original_band]
                if isinstance(views[title], int):
                    if new_row_index != views[title]:
                        continue

                if title in ["3D Overview", "Top View"]:
                    band_offset = band_new_y_start[original_band]
                    local_y_offset = p["y"] - (original_band * ROW_HEIGHT)

                    y_plot = band_offset + local_y_offset
                    y_e_plot = y_plot + (p["y_e"] - p["y"])
                else:
                    y_plot = p["y"]
                    y_e_plot = p["y_e"]

                faces = cuboid_faces_from_extents(
                    p["x"], y_plot, p["z"],
                    p["x_e"], y_e_plot, p["z_e"]
                )

                color = row_colors.get(new_row_index, "gray")

                ax.add_collection3d(Poly3DCollection(
                        faces,
                        facecolor=color,
                        edgecolor="k",
                        alpha=0.35,
                        zsort='average'

                    )
                )

                cx = (p["x"] + p["x_e"]) / 2
                cy = (y_plot + y_e_plot) / 2
                cz = p["z_e"] - 350

                ax.text(
                    cx,
                    cy,
                    cz,
                    denote.get(p["item"], "?"),
                    ha="center",
                    va="center",
                    fontsize=9,
                    fontweight="bold",
                    color="black",
                )

            ax.set_yticks([])
            ax.yaxis.pane.set_visible(False)
            ax.zaxis.pane.set_visible(False)

            elev, azim = view_angles[title]
            ax.view_init(elev=elev, azim=azim)

            ax.set_title(title)
            ax.set_xlim(x_max, 0)
            ax.set_ylim(0, y_max)
            ax.set_zlim(0, z_max)
            ax.set_box_aspect((x_max, y_max, z_max))
            ax.set_xlabel("X")
        ax = fig.add_subplot(3, 4, 6)
        x_bins = compute_x_weight_bins(placements, 1000, 14000)

        xs = []
        loads = []
        allowed = []

        for x in range(0, int(np.ceil(float(x_max))), 1000):
            xs.append(x + 500) 
            loads.append(x_bins.get(x, 0.0))
            allowed.append(allowed_weight_at_x(x + 500, chart))
        ax.plot(xs, allowed, label="Allowed Weight", color="red", linestyle="--")
        ax.plot(xs, loads, label="Occupied Weight", color="green",linestyle="--")
        ax.set_xlabel("Length (mm)")
        ax.set_ylabel("Weight (Kg)")
        ax.set_title("Distribution Curve")
        ax.legend()
        ax.grid(True)
    
        legend_text = "\n".join(
            f"{k} = {denote[k]} : {assigned_items.get(k, 0)} assigned, {un.get(k, 0)} unassigned"
            for k in selected_keys
        )
        legend_text_with_title = (
            f"Container type: {_ct}\n"
            f"Loading: {_ln or '—'}  |  Operator: {_on or '—'}  |  Client: {_cn or '—'}\n"
            f"Version: {_vn or '—'}  |  Changer: {_vch or '—'}\n"
            "-------------------------------------------------------------\n"
            "Selected materials only — symbol ↔ assigned / unassigned counts\n"
            "-------------------------------------------------------------\n"
            f"{legend_text}\n"
            "-------------------------------------------------------------\n"
            "Container Satistics\n"
            "-------------------------------------------------------------\n"
            f"Load Weight: {weight:.2f} kg\n"
            f"Container Occupier Volume: {volume:.2f} m³\n"
            f"Container Remaining Volume: {remaining_volume:.2f} m³\n"
            "-------------------------------------------------------------\n"
        )
        fig.text(
            0.6, 0.5,
            legend_text_with_title,
            fontsize=11,
            va="center",
            ha="left"

        )
        plt.tight_layout()
        st.pyplot(fig)
        _export_ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        st.session_state._last_plot_export_ts = _export_ts
        st.session_state._last_plot_client_slug = _safe_filename_part(_cn)
        _pbuf = io.BytesIO()
        fig.savefig(_pbuf, format="png", dpi=120, bbox_inches="tight")
        plot_png = _pbuf.getvalue()
        st.session_state._last_plot_png = plot_png
        plot_pdf = b""
        try:
            _pdfbuf = io.BytesIO()
            fig.savefig(_pdfbuf, format="pdf", bbox_inches="tight")
            plot_pdf = _pdfbuf.getvalue()
        except Exception:
            pass
        st.session_state._last_plot_pdf = plot_pdf
        if not st.session_state.get("_result_saved_once"):
            if _stor():
                try:
                    rid = storage.save_run(
                        client=_meta_client_name() or "unknown",
                        loading_name=_ln,
                        operator_name=_on,
                        version_name=_meta_version_name(),
                        changer=_meta_changer(),
                        container_type=str(_ct),
                        quantities={
                            k: int(st.session_state["quantities"][k])
                            for k in selected_keys
                        },
                        load_data=st.session_state.load_data,
                        forbidden_on=st.session_state.forbidden_on_data,
                        plot_png=plot_png,
                        material_xlsx=st.session_state.get("persist_material_xlsx"),
                        stacking_xlsx=st.session_state.get("persist_stacking_xlsx"),
                    )
                    if rid:
                        st.success("Saved to MinIO (material / stacking / plot).")
                except Exception as e:
                    st.warning(f"Could not save to MinIO: {e}")
            elif storage is not None and storage.storage_enabled() and not storage.minio_available():
                st.info(
                    "MinIO save skipped: install **minio** (`pip install minio`). "
                    "Use **Download result report (PDF)** below to keep a local copy."
                )
            st.session_state._result_saved_once = True
        plt.close(fig)
        st.session_state["_pack_result_cache"] = {
            "fp": _fp,
            "placements": deepcopy(placements),
            "un": dict(un),
            "assigned_items": dict(assigned_items),
            "weight": weight,
            "volume": volume,
            "remaining_volume": remaining_volume,
            "denote": dict(denote),
            "plot_png": plot_png,
            "plot_pdf": plot_pdf,
            "export_ts": _export_ts,
            "client_slug": _safe_filename_part(_cn),
        }

    _ln = (st.session_state.get("loading_run_name") or "").strip()
    _on = (st.session_state.get("operator_name") or "").strip()
    _png = st.session_state.get("_last_plot_png")
    _pdf = st.session_state.get("_last_plot_pdf") or b""
    _pdf_ts = st.session_state.get("_last_plot_export_ts") or datetime.now().strftime("%Y-%m-%d_%H%M%S")
    _pdf_cli = st.session_state.get("_last_plot_client_slug") or _safe_filename_part(
        _meta_client_name() or ""
    )
    _pdf_name = f"{_pdf_ts}_{_pdf_cli}_load_optimization.pdf"
    if _pdf:
        st.download_button(
            "Download result report (PDF)",
            _pdf,
            file_name=_pdf_name,
            mime="application/pdf",
            key="res_dl_pdf_btn",
        )
    elif _png:
        _pdf_fallback = _png_bytes_to_pdf(_png)
        if _pdf_fallback:
            st.download_button(
                "Download result report (PDF)",
                _pdf_fallback,
                file_name=_pdf_name,
                mime="application/pdf",
                key="res_dl_pdf_fallback_btn",
            )
