from __future__ import annotations

import streamlit as st
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, date, timedelta
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
        f'<div id="schnellecke-header" style="display:flex;justify-content:center;width:100%;margin:0.25rem 0 0.75rem 0;">'
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


def parse_catalog_excel(buf) -> tuple[list[tuple[str, date]], list[str]]:
    """
    Parse a "full catalog" file (e.g. time.XLSX) into one entry per row:
    `(material_key, Abholtermin date)`. Returns the entries plus a list of
    skipped material numbers (date or material missing).
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
    c_date = _match_column_by_patterns(
        df,
        [
            "abholtermin",
            "abholdatum",
            "pickupdate",
            "pickup date",
            "collectiondate",
            "collection date",
            "liefertermin",
            "lieferdatum",
            "deliverydate",
            "delivery date",
            "duedate",
            "due date",
        ],
    )
    if not c_mat:
        raise ValueError(
            "Catalog file needs a Material column (Material / Materialnummer). "
            f"Found: {', '.join(map(str, df.columns))}"
        )
    if not c_date:
        raise ValueError(
            "Catalog file needs an **Abholtermin** (or pickup/delivery date) column. "
            f"Found: {', '.join(map(str, df.columns))}"
        )

    out: list[tuple[str, date]] = []
    skipped: list[str] = []
    for _, r in df.iterrows():
        m = normalize_materialnummer(r.get(c_mat))
        raw_d = r.get(c_date)
        if m is None:
            continue
        if raw_d is None or (isinstance(raw_d, float) and np.isnan(raw_d)):
            skipped.append(m)
            continue
        try:
            ts = pd.to_datetime(raw_d, errors="coerce")
        except (TypeError, ValueError):
            ts = pd.NaT
        if pd.isna(ts):
            skipped.append(m)
            continue
        out.append((m, ts.date()))
    return out, skipped


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

def pack_once(container_type, items, chart, forbidden_on, resort=True):
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

    # Only re-sort when the caller hasn't already chosen an ordering (e.g.
    # pack_3d supplies randomised / volume-sorted seeds that must be preserved).
    if resort:
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
    best_score = (-1, -1, -1.0)
    best_raw = []

    load_ref = {}
    for n, b in items:
        load_ref[n] = b

    # Seed orderings: the first is the legacy length-ascending sort (so single-
    # truck results never regress), followed by a handful of heuristic sorts
    # that are strong for bin packing (largest-volume first, longest first,
    # heaviest first). Any remaining runs are genuine random permutations.
    seeds: list[list] = [
        sorted(items, key=lambda x: x[1]["length"]),
        sorted(items, key=lambda x: -(x[1]["length"] * x[1]["width"] * x[1]["height"])),
        sorted(items, key=lambda x: -x[1]["length"]),
        sorted(items, key=lambda x: -x[1]["weight"]),
        sorted(items, key=lambda x: (-x[1]["height"], -x[1]["length"])),
    ]

    for r in range(max(1, runs)):
        if r < len(seeds):
            candidate_items = seeds[r]
        else:
            candidate_items = items[:]
            random.shuffle(candidate_items)

        placements = pack_once(
            container_type, candidate_items, chart, forbidden_on, resort=False
        )
        occ_vol = sum(p["l"] * p["w"] * p["h"] for p in placements)
        # Prefer more items, then more volume, then more weight.
        score = (len(placements), occ_vol, sum(p["weight"] for p in placements))

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


def _detect_natural_rows(placements, container_width):
    """
    Decide how many side-by-side rows (1–3) fit the truck for the given item
    set, using the widest item as the binding budget so the layout is safe even
    when widths are mixed. Returns the Y-center of each row.
    """
    if not placements:
        return []
    GAP_Y = 30
    available = float(container_width)
    widest = max(float(p["w"]) for p in placements)
    if widest <= 0:
        return [available / 2.0]

    n_rows = 1
    used = widest
    while n_rows < 3 and used + GAP_Y + widest <= available:
        used += GAP_Y + widest
        n_rows += 1

    if n_rows == 1:
        centers = [available / 2.0]
    elif n_rows == 2:
        c1 = widest / 2.0 + GAP_Y
        c2 = available - widest / 2.0 - GAP_Y
        centers = [c1, c2]
    else:
        step = available / 3.0
        centers = [step / 2.0, step + step / 2.0, 2 * step + step / 2.0]
    return centers


def systematic_layout(placements, container_type, chart, load_ref, forbidden_on=None):
    """
    Reorganize an existing valid packing into a warehouse-style "systematic"
    layout that's easy for a loader to follow:

      * All items of the same material are grouped into one or more vertical
        stacks (one column per stack).
      * Stack height is capped by the material's `stapelfaktor` and the
        container height — no half-empty stacks just because the packer ran
        out of space partway through a material.
      * Each row uses a single orientation (the bottom item's L/W), so items
        line up cleanly without diagonal gaps.
      * Stacks are placed row-by-row, longest first, balancing rows by their
        current X position.

    Falls back to the input `placements` if the systematic layout would
    overflow the container length, overlap, or violate weight / forbidden_on /
    stapelfaktor rules.
    """
    if not placements:
        return placements

    c = container[container_type]
    forbidden_on = forbidden_on or {}

    by_mat: dict[str, list[dict]] = defaultdict(list)
    for p in placements:
        by_mat[p["item"]].append(p)

    stacks: list[list[dict]] = []
    for mat, items in by_mat.items():
        if not items:
            continue
        sf = _stapelfaktor_from_box(load_ref.get(mat, {}))
        item_h = items[0]["h"]
        max_by_height = max(1, int(c["height"] // max(1, item_h)))
        stack_size = max(1, min(int(sf), max_by_height, len(items)))
        items_sorted = sorted(items, key=lambda p: -p["weight"])
        for i in range(0, len(items_sorted), stack_size):
            stacks.append(items_sorted[i:i + stack_size])

    if not stacks:
        return placements

    widest = max(p["w"] for p in placements)
    GAP_Y = 30
    n_rows = max(1, min(3, int((c["width"] + GAP_Y) // (widest + GAP_Y))))

    if n_rows == 1:
        centers = [c["width"] / 2.0]
    elif n_rows == 2:
        centers = [widest / 2.0 + GAP_Y, c["width"] - widest / 2.0 - GAP_Y]
    else:
        step = c["width"] / 3.0
        centers = [step / 2.0, step + step / 2.0, 2 * step + step / 2.0]

    stacks.sort(
        key=lambda stk: (
            -stk[0]["l"],
            -sum(p["weight"] for p in stk),
            -len(stk),
        )
    )

    # No forced spacing — items sit flush against each other, exactly as a
    # warehouse loader would push them.  Even small gaps add up across many
    # columns and used to leave whole stacks unplaced (forcing a fallback
    # to the raw pack_3d output, which is what the user saw as a single
    # isolated item floating in the middle of a row).
    GAP_X = 0
    FRONT_X = 0
    row_x = [FRONT_X] * n_rows
    new_placements: list[dict] = []

    for stk in stacks:
        bot = stk[0]
        l = float(bot["l"])
        w = float(bot["w"])

        # Pick the row with the smallest current X cursor; if it cannot
        # accommodate this stack, try every other row before giving up.
        row_order = sorted(range(n_rows), key=lambda r: row_x[r])
        row_idx = None
        for r in row_order:
            if row_x[r] + l <= c["length"]:
                row_idx = r
                break
        if row_idx is None:
            continue
        x = row_x[row_idx]

        cy = centers[row_idx]
        y0 = cy - w / 2.0
        y1 = y0 + w
        if y0 < 0:
            y0, y1 = 0.0, w
        if y1 > c["width"]:
            y1, y0 = float(c["width"]), float(c["width"]) - w

        z_cursor = 0.0
        layers_for_stack: list[dict] = []
        for p in stk:
            np_ = dict(p)
            np_["x"] = x
            np_["x_e"] = x + l
            np_["y"] = y0
            np_["y_e"] = y1
            np_["z"] = z_cursor
            np_["z_e"] = z_cursor + p["h"]
            if z_cursor + p["h"] > c["height"]:
                break
            if layers_for_stack and violates_forbidden(np_, layers_for_stack, forbidden_on):
                break
            layers_for_stack.append(np_)
            z_cursor += p["h"]

        if not layers_for_stack:
            continue
        new_placements.extend(layers_for_stack)
        row_x[row_idx] += l + GAP_X

    if len(new_placements) < len(placements):
        return placements

    for i, a in enumerate(new_placements):
        for b in new_placements[i + 1:]:
            if overlaps(a, b):
                return placements

    if not placements_respect_stapelfaktor(new_placements, load_ref):
        return placements

    bins = compute_x_weight_bins(new_placements, x_max=c["length"])
    bs = 1000
    for x_bin, w_in_bin in bins.items():
        if w_in_bin > allowed_weight_at_x(x_bin + bs / 2, chart):
            return placements

    return new_placements


def smooth_row_heights(placements, container_type, chart, load_ref):
    """
    Visual cleanup that **preserves pack_3d's stacks** (so the truck's fill %
    is not lost) and only reorders columns within each row so:

      * the tallest stacks sit at the **front** of the truck and heights
        descend smoothly toward the back (no random "skyline" of tall
        boxes next to single short ones);
      * columns sit flush against each other with only a tiny visual
        margin so the truck still looks dense.

    A "column" here is a set of items that share the same X start in the
    original packing — these were already stacked on top of each other by
    `pack_once`, and we never break those stacks.

    Falls back to the original packing if any safety check fails.
    """
    if not placements:
        return placements

    c = container[container_type]
    centers = _detect_natural_rows(placements, c["width"])
    n_rows = len(centers)
    if n_rows == 0:
        return placements

    rows: list[list[dict]] = [[] for _ in range(n_rows)]
    for p in placements:
        cy_p = (p["y"] + p["y_e"]) / 2.0
        nearest = min(range(n_rows), key=lambda i: abs(centers[i] - cy_p))
        rows[nearest].append(p)

    # Tiny visual gap so adjacent columns don't visually merge, but no
    # forced front offset — every mm of truck length should be usable.
    GAP_X = 10
    FRONT_X = 0
    new_placements: list[dict] = []

    for row_idx, items in enumerate(rows):
        if not items:
            continue

        cols: dict[int, list[dict]] = defaultdict(list)
        for p in items:
            cols[round(p["x"])].append(p)

        ordered = sorted(
            cols.values(),
            key=lambda col: (
                -max(p["z_e"] for p in col),
                -sum(p["h"] for p in col),
                -max(p["l"] for p in col),
            ),
        )

        x_cursor = FRONT_X
        cy = centers[row_idx]
        for col in ordered:
            col.sort(key=lambda p: p["z"])
            col_l = max(p["l"] for p in col)
            col_w = max(p["w"] for p in col)

            y0 = cy - col_w / 2.0
            y1 = y0 + col_w
            if y0 < 0:
                y0, y1 = 0.0, col_w
            if y1 > c["width"]:
                y1, y0 = float(c["width"]), float(c["width"]) - col_w

            for p in col:
                np_ = dict(p)
                np_["x"] = x_cursor
                np_["x_e"] = x_cursor + p["l"]
                inner_off = (col_w - p["w"]) / 2.0
                np_["y"] = y0 + inner_off
                np_["y_e"] = np_["y"] + p["w"]
                new_placements.append(np_)
            x_cursor += col_l + GAP_X

        if x_cursor > c["length"] + FRONT_X:
            return placements

    for i, a in enumerate(new_placements):
        for b in new_placements[i + 1:]:
            if overlaps(a, b):
                return placements

    if not placements_respect_stapelfaktor(new_placements, load_ref):
        return placements

    bins = compute_x_weight_bins(new_placements, x_max=c["length"])
    bs = 1000
    for x_bin, w_in_bin in bins.items():
        if w_in_bin > allowed_weight_at_x(x_bin + bs / 2, chart):
            return placements

    return new_placements


def _try_fit_into_existing(
    host_placements, extra_items, container_type, chart, forbidden_on
):
    """
    Try to add `extra_items` on top of / next to an *existing* packing without
    moving any host item. For each extra item we sweep candidate positions:
    on top of every host item, then to the right of every host item, then on
    the floor at the back of the truck. The first position that passes all
    physical constraints (overlap, weight curve, forbidden_on, stapelfaktor,
    corner support) wins. Items that don't fit are simply skipped.

    Returns the augmented placement list. Host items are returned unchanged
    (positions / extents preserved).
    """
    placements = [dict(p) for p in host_placements]
    c = container[container_type]

    items_sorted = sorted(
        extra_items,
        key=lambda kb: kb[1]["length"] * kb[1]["width"] * kb[1]["height"],
    )

    for name, box in items_sorted:
        sf = _stapelfaktor_from_box(box)
        rotations = [
            (box["length"], box["width"], box["height"]),
            (box["width"], box["length"], box["height"]),
        ]

        # Collect candidate (x, y, z) anchors. Prefer top-of-stack first so
        # small items naturally ride on bigger ones.
        seen: set[tuple[int, int, int]] = set()
        candidates: list[tuple[float, float, float]] = []

        def _push(x, y, z):
            key = (round(x), round(y), round(z))
            if key in seen:
                return
            seen.add(key)
            candidates.append((x, y, z))

        for p in placements:
            _push(p["x"], p["y"], p["z_e"])
        for p in placements:
            _push(p["x_e"] + 30, p["y"], 0)
        for p in placements:
            _push(p["x"], p["y_e"] + 30, 0)
        max_x = max((p["x_e"] for p in placements), default=30)
        _push(30, 30, 0)
        _push(max_x + 30, 30, 0)

        placed = False
        for px, py, pz in candidates:
            if placed:
                break
            for l, w, h in rotations:
                if px < 0 or py < 0 or pz < 0:
                    continue
                if px + l > c["length"] or py + w > c["width"] or pz + h > c["height"]:
                    continue
                candidate = {
                    "item": name,
                    "x": px, "y": py, "z": pz,
                    "x_e": px + l, "y_e": py + w, "z_e": pz + h,
                    "l": l, "w": w, "h": h,
                    "weight": box["weight"],
                    "pallet_type": box["pallet_type"],
                }
                if any(overlaps(candidate, p) for p in placements):
                    continue
                if pz > 0 and not has_corner_support(candidate, placements):
                    continue
                if violates_forbidden(candidate, placements, forbidden_on):
                    continue
                if violates_stapelfaktor(candidate, placements, sf):
                    continue
                trial = placements + [candidate]
                bins = compute_x_weight_bins(trial, x_max=c["length"])
                if any(
                    bins[xb] > allowed_weight_at_x(xb + 500, chart) for xb in bins
                ):
                    continue
                placements.append(candidate)
                placed = True
                break

    return placements


def _consolidate_pack_once(host_kvs, tail_kvs, container_type, chart, forbidden_on, runs):
    """
    Repack `host + tail` items into a single container with packings biased
    toward keeping every host item placed. Tries a handful of host-first
    seedings (legacy / volume-desc / weight-desc), then a few random shuffles.
    Returns the largest placement set found.
    """
    all_kvs = host_kvs + tail_kvs
    tail_small_first = sorted(
        tail_kvs, key=lambda x: x[1]["length"] * x[1]["width"] * x[1]["height"]
    )
    tail_large_first = sorted(
        tail_kvs, key=lambda x: -(x[1]["length"] * x[1]["width"] * x[1]["height"])
    )

    seeds: list[list] = [
        sorted(all_kvs, key=lambda x: x[1]["length"]),
        sorted(all_kvs, key=lambda x: -(x[1]["length"] * x[1]["width"] * x[1]["height"])),
        sorted(host_kvs, key=lambda x: x[1]["length"]) + tail_small_first,
        sorted(host_kvs, key=lambda x: -(x[1]["length"] * x[1]["width"] * x[1]["height"]))
        + tail_small_first,
        sorted(host_kvs, key=lambda x: -x[1]["weight"]) + tail_small_first,
        tail_small_first
        + sorted(host_kvs, key=lambda x: -(x[1]["length"] * x[1]["width"] * x[1]["height"])),
        sorted(host_kvs, key=lambda x: -x[1]["height"]) + tail_large_first,
    ]

    best: list[dict] = []
    best_score = (-1, -1.0, -1.0)
    for seed in seeds:
        plc = pack_once(container_type, seed, chart, forbidden_on, resort=False)
        score = (
            len(plc),
            sum(p["l"] * p["w"] * p["h"] for p in plc),
            sum(p["weight"] for p in plc),
        )
        if score > best_score:
            best, best_score = plc, score

    extra = max(0, runs - len(seeds))
    for _ in range(extra):
        shuffled = all_kvs[:]
        random.shuffle(shuffled)
        plc = pack_once(container_type, shuffled, chart, forbidden_on, resort=False)
        score = (
            len(plc),
            sum(p["l"] * p["w"] * p["h"] for p in plc),
            sum(p["weight"] for p in plc),
        )
        if score > best_score:
            best, best_score = plc, score

    return best


def pack_multi_trucks(
    container_type: str,
    dated_items: list[tuple[str, dict, date]],
    backup_days: int,
    chart,
    forbidden_on: dict,
    runs: int = 100,
    progress=None,
) -> tuple[list[dict], list[tuple[str, date]]]:
    """
    Greedy bucketed packing for catalog mode.

    Items are sorted by Abholtermin. Each "bucket" starts at the earliest unassigned date
    and includes all later items whose date is within `backup_days` of that anchor.
    A bucket is poured into trucks one after another (filling each fully via `pack_3d`)
    until empty or no further item fits. The next bucket always starts a new truck —
    so a half-full truck whose deadline has passed will not pick up far-future items.

    After each bucket is poured we run a small consolidation pass: any trailing
    trucks whose combined items fit in one truck are merged, so we don't leave
    a half-empty truck dangling when its contents could have ridden in the
    previous one.

    `progress` (optional) is a callable `fn(stage: str, done: int, total: int, detail: str)`
    invoked after each truck is packed so the caller can update a UI.

    Returns `(trucks, unplaceable)`.
    """
    sorted_items = sorted(dated_items, key=lambda t: (t[2], t[0]))
    n = len(sorted_items)
    cont = container[container_type]
    cont_vol_m3 = (cont["length"] * cont["width"] * cont["height"]) / 1e9

    def _make_truck(placements, placed_entries, anchor, window_end):
        occ_vol = sum(p["l"] * p["w"] * p["h"] for p in placements) / 1e9
        return {
            "placements": [dict(p) for p in placements],
            "items_dates": [(k, d) for (k, _b, d) in placed_entries],
            "_entries": list(placed_entries),  # kept for consolidation, stripped before return
            "anchor_date": anchor,
            "window_end": window_end,
            "container_type": container_type,
            "fill_volume_m3": occ_vol,
            "fill_pct": (occ_vol / cont_vol_m3 * 100.0) if cont_vol_m3 > 0 else 0.0,
            "weight_kg": sum(p["weight"] for p in placements),
        }

    def _entries_to_truck(entries, placements, anchor, window_end):
        load_ref = {k: b for (k, b, _) in entries}
        placements = smooth_row_heights(
            placements, container_type, chart, load_ref
        )
        need = Counter(p["item"] for p in placements)
        placed_entries, kept = [], []
        for entry in entries:
            if need[entry[0]] > 0:
                placed_entries.append(entry)
                need[entry[0]] -= 1
            else:
                kept.append(entry)
        return _make_truck(placements, placed_entries, anchor, window_end), kept

    def _pack_entries(entries, anchor, window_end, runs_override=None):
        placements, _un, _placed = pack_3d(
            container_type,
            [(k, b) for (k, b, _) in entries],
            chart,
            forbidden_on,
            runs=runs_override if runs_override is not None else runs,
        )
        if not placements:
            return None, list(entries)
        return _entries_to_truck(entries, placements, anchor, window_end)

    def _consolidate_into_host(host_entries, tail_entries, anchor, window_end, runs_override):
        host_kvs = [(k, b) for (k, b, _) in host_entries]
        tail_kvs = [(k, b) for (k, b, _) in tail_entries]
        all_entries = list(host_entries) + list(tail_entries)

        # Strategy A: keep the host's already-packed truck intact and just slot
        # tail items on top of / next to existing items. This is the cheapest
        # and most "respectful" merge — host items don't move at all.
        host_truck = next(
            (t for t in bucket_trucks if t["_entries"] == host_entries), None
        )
        if host_truck is not None:
            plc_a = _try_fit_into_existing(
                host_truck["placements"], tail_kvs,
                container_type, chart, forbidden_on,
            )
            need_a = Counter(p["item"] for p in plc_a)
            if sum(need_a.values()) > sum(
                Counter(p["item"] for p in host_truck["placements"]).values()
            ):
                cand_a, kept_a = _entries_to_truck(
                    all_entries, plc_a, anchor, window_end
                )
                if cand_a is not None and len(cand_a["_entries"]) > len(host_entries):
                    return cand_a, kept_a

        # Strategy B: full re-pack with host-first seedings.
        plc = _consolidate_pack_once(
            host_kvs, tail_kvs, container_type, chart, forbidden_on,
            runs=runs_override,
        )
        if not plc:
            return None, list(host_entries) + list(tail_entries)
        return _entries_to_truck(all_entries, plc, anchor, window_end)

    trucks: list[dict] = []
    unplaceable: list[tuple[str, date]] = []

    total_items_for_progress = n
    items_placed_so_far = 0

    i = 0
    while i < n:
        anchor = sorted_items[i][2]
        window_end = anchor + timedelta(days=int(max(0, backup_days)))
        j = i
        bucket: list[tuple[str, dict, date]] = []
        while j < n and sorted_items[j][2] <= window_end:
            bucket.append(sorted_items[j])
            j += 1

        bucket_trucks: list[dict] = []
        remaining = list(bucket)
        while remaining:
            truck, remaining = _pack_entries(remaining, anchor, window_end)
            if truck is None:
                for k, _b, d in remaining:
                    unplaceable.append((k, d))
                remaining = []
                break
            bucket_trucks.append(truck)
            items_placed_so_far += len(truck["_entries"])
            if progress is not None:
                try:
                    progress(
                        "pack",
                        items_placed_so_far,
                        total_items_for_progress,
                        f"Truck {len(trucks) + len(bucket_trucks)} · "
                        f"{truck['fill_pct']:.0f}% fill · {len(truck['_entries'])} items",
                    )
                except Exception:
                    pass

        # Consolidation: while the bucket's tail truck is under-filled, try to
        # absorb it into any earlier truck in the same bucket. The packer used
        # here is host-first biased — it preserves the host's items and only
        # tries to slot the tail's items into the remaining space. Accepts
        # partial absorption (the tail shrinks) as long as it makes progress.
        CONSOLIDATE_RUNS = max(20, runs)
        UNDERFILL_THRESHOLD = 60.0
        SAFETY_PASSES = 8
        for _pass in range(SAFETY_PASSES):
            if len(bucket_trucks) < 2:
                break
            tail = bucket_trucks[-1]
            if tail["fill_pct"] >= UNDERFILL_THRESHOLD:
                break

            absorbed = False
            for host_idx in range(len(bucket_trucks) - 1):
                host = bucket_trucks[host_idx]
                merged, leftover_entries = _consolidate_into_host(
                    host["_entries"], tail["_entries"], anchor, window_end,
                    runs_override=CONSOLIDATE_RUNS,
                )
                if merged is None:
                    continue
                merged_count = len(merged["_entries"])
                host_count = len(host["_entries"])
                tail_count = len(tail["_entries"])
                # Reject if no tail items got absorbed.
                if merged_count <= host_count:
                    continue

                if not leftover_entries:
                    bucket_trucks[host_idx] = merged
                    bucket_trucks.pop()
                    absorbed = True
                    if progress is not None:
                        try:
                            progress(
                                "consolidate",
                                items_placed_so_far,
                                total_items_for_progress,
                                f"Tail merged into truck {len(trucks) + host_idx + 1} "
                                f"→ {merged['fill_pct']:.0f}% fill",
                            )
                        except Exception:
                            pass
                    break

                # Partial absorb: re-pack the leftovers into a new (smaller) tail.
                new_tail, _ = _pack_entries(
                    leftover_entries, anchor, window_end, runs_override=CONSOLIDATE_RUNS
                )
                if new_tail is None:
                    continue
                if len(new_tail["_entries"]) >= tail_count:
                    continue

                bucket_trucks[host_idx] = merged
                bucket_trucks[-1] = new_tail
                absorbed = True
                if progress is not None:
                    try:
                        progress(
                            "consolidate",
                            items_placed_so_far,
                            total_items_for_progress,
                            f"Pushed {merged_count - host_count} item(s) "
                            f"from tail into truck {len(trucks) + host_idx + 1}",
                        )
                    except Exception:
                        pass
                break

            if not absorbed:
                break

        trucks.extend(bucket_trucks)
        i = j

    # ===== Cross-bucket forward consolidation =====
    # Allow an under-filled truck's items to ride a *later* truck if the
    # delivery delay (later_truck.anchor − item.date) is within `backup_days`.
    # We never move items the other way (an item can always be delivered
    # earlier — that was already handled by within-bucket packing).
    def _refresh_truck(t):
        occ = sum(p["l"] * p["w"] * p["h"] for p in t["placements"]) / 1e9
        t["fill_volume_m3"] = occ
        t["fill_pct"] = (occ / cont_vol_m3 * 100.0) if cont_vol_m3 > 0 else 0.0
        t["weight_kg"] = sum(p["weight"] for p in t["placements"])
        t["items_dates"] = [(k, d) for (k, _b, d) in t["_entries"]]
        if t["_entries"]:
            t["anchor_date"] = min(d for (_k, _b, d) in t["_entries"])

    UNDERFILL_FORWARD = 50.0
    FORWARD_PASSES = 6
    trucks.sort(key=lambda t: t["anchor_date"])
    for _fpass in range(FORWARD_PASSES):
        moved_anything = False
        i = 0
        while i < len(trucks):
            t = trucks[i]
            if t["fill_pct"] >= UNDERFILL_FORWARD or not t["_entries"]:
                i += 1
                continue

            for j in range(i + 1, len(trucks)):
                t_later = trucks[j]
                # Bind against the *latest* date already in the host truck:
                # adding our item shouldn't cause the host's effective
                # delivery (its latest item) to exceed item.date + backup_days.
                if not t_later["_entries"]:
                    continue
                t_later_latest = max(d for (_k, _b, d) in t_later["_entries"])

                eligible_indices: list[int] = []
                for idx, (_k, _b, d) in enumerate(t["_entries"]):
                    delay_days = (t_later_latest - d).days
                    if 0 <= delay_days <= backup_days:
                        eligible_indices.append(idx)
                if not eligible_indices:
                    continue

                eligible_kvs = [
                    (t["_entries"][idx][0], t["_entries"][idx][1])
                    for idx in eligible_indices
                ]
                old_count = len(t_later["placements"])
                new_placements = _try_fit_into_existing(
                    t_later["placements"], eligible_kvs,
                    container_type, chart, forbidden_on,
                )
                if len(new_placements) <= old_count:
                    continue

                placed_extras = new_placements[old_count:]
                placed_names = Counter(p["item"] for p in placed_extras)
                moved_entries: list[tuple[str, dict, date]] = []
                kept_entries: list[tuple[str, dict, date]] = []
                eligible_set = set(eligible_indices)
                for idx, entry in enumerate(t["_entries"]):
                    if idx in eligible_set and placed_names.get(entry[0], 0) > 0:
                        moved_entries.append(entry)
                        placed_names[entry[0]] -= 1
                    else:
                        kept_entries.append(entry)

                if not moved_entries:
                    continue

                # Snapshot the host's pre-merge state so we can roll back
                # cleanly if the donor's leftover-repack fails. We must take
                # the snapshot *before* smoothing, because smoothing reorders
                # the placements list.
                host_snapshot = {
                    "placements": [dict(p) for p in t_later["placements"]],
                    "_entries": list(t_later["_entries"]),
                    "fill_volume_m3": t_later["fill_volume_m3"],
                    "fill_pct": t_later["fill_pct"],
                    "weight_kg": t_later["weight_kg"],
                    "items_dates": list(t_later["items_dates"]),
                    "anchor_date": t_later["anchor_date"],
                }

                merged_entries = list(t_later["_entries"]) + moved_entries
                load_ref = {k: b for (k, b, _) in merged_entries}
                t_later["placements"] = smooth_row_heights(
                    new_placements, container_type, chart, load_ref
                )
                t_later["_entries"] = merged_entries
                _refresh_truck(t_later)

                if not kept_entries:
                    removed_count = len(moved_entries)
                    trucks.pop(i)
                    if progress is not None:
                        try:
                            progress(
                                "forward",
                                items_placed_so_far,
                                total_items_for_progress,
                                f"Forwarded all {removed_count} item(s) of an "
                                f"under-filled truck into a later truck "
                                f"(within {backup_days}-day delay window)",
                            )
                        except Exception:
                            pass
                    moved_anything = True
                    break

                rep_pack, _ = _pack_entries(
                    kept_entries, t["anchor_date"], t["window_end"],
                    runs_override=max(20, runs // 2),
                )
                if rep_pack is None:
                    t_later.update(host_snapshot)
                    continue

                trucks[i] = rep_pack
                if progress is not None:
                    try:
                        progress(
                            "forward",
                            items_placed_so_far,
                            total_items_for_progress,
                            f"Forwarded {len(moved_entries)} item(s) into a "
                            f"later truck, repacked the remainder",
                        )
                    except Exception:
                        pass
                moved_anything = True
                break

            if not moved_anything:
                i += 1
            else:
                trucks.sort(key=lambda t: t["anchor_date"])
                break

        if not moved_anything:
            break

    # Renumber happens implicitly at render time (truck index = position).
    for t in trucks:
        t.pop("_entries", None)

    return trucks, unplaceable


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


def _build_truck_figure(
    container_type: str,
    placements: list[dict],
    selected_keys: list[str],
    denote: dict[str, str],
    weight: float,
    occ_volume_m3: float,
    remaining_volume_m3: float,
    assigned_items: dict[str, int],
    header_text: str,
    extra_legend_lines: str = "",
):
    """
    Same 5-views + distribution-curve + legend layout as the single-run result page,
    sized for one truck. Returns the matplotlib figure (caller closes it).
    """
    c = container[container_type]
    x_max, y_max, z_max = c["length"], c["width"], c["height"]

    NUM_ROWS = 3
    ROW_HEIGHT = y_max / NUM_ROWS
    bands: dict[int, list[dict]] = {0: [], 1: [], 2: []}
    for p in placements:
        y_center = (p["y"] + p["y_e"]) / 2
        bi = int(y_center // ROW_HEIGHT)
        bi = min(bi, NUM_ROWS - 1)
        bands[bi].append(p)

    band_metrics: dict[int, tuple[float, float, float]] = {}
    for band, items_in_band in bands.items():
        if not items_in_band:
            band_metrics[band] = (0, 0, 0)
        else:
            band_metrics[band] = (
                sum(p["weight"] for p in items_in_band),
                max(p["x_e"] for p in items_in_band),
                sum(p["h"] for p in items_in_band),
            )
    sorted_bands = sorted(band_metrics.items(), key=lambda x: (-x[1][0], -x[1][1], -x[1][2]))
    band_remap: dict[int, int] = {}
    for new_idx, (orig, _) in enumerate(sorted_bands):
        band_remap[orig] = new_idx
    for b in bands.keys():
        if b not in band_remap:
            band_remap[b] = len(band_remap)
    band_new_y_start = {orig: band_remap[orig] * ROW_HEIGHT for orig in range(NUM_ROWS)}

    views = {"3D Overview": "all", "Row 1": 0, "Row 2": 1, "Row 3": 2, "Top View": "all"}
    row_colors = {0: "blue", 1: "red", 2: "green"}
    view_angles = {
        "3D Overview": (30, 110),
        "Row 1": (0, 90),
        "Row 2": (0, 90),
        "Row 3": (0, 90),
        "Top View": (90, 90),
    }

    fig = plt.figure(figsize=(20, 12))
    fig.suptitle(header_text, fontsize=11, y=0.995)
    # Same 3×4 cell layout as the original single-truck figure so plot panels
    # keep their full size; the legend takes the otherwise-empty bottom-right
    # block (rows 1–2, cols 2–3).
    gs = fig.add_gridspec(3, 4, hspace=0.30, wspace=0.25)
    plot_axes = [
        gs[0, 0], gs[0, 1], gs[0, 2], gs[0, 3],  # 3D Overview, Row 1, Row 2, Row 3
        gs[1, 0],  # Top View
    ]
    distribution_slot = gs[1, 1]
    legend_slot = gs[1:3, 2:4]

    def _draw_container_wireframe(ax, x0, y0, z0, x1, y1, z1):
        """Outline the container in a soft grey wireframe so the user can
        see the truck's boundary in every view (the previous chart had no
        explicit boundary, which made loads near the back look like they
        were spilling out)."""
        edges = [
            ((x0, y0, z0), (x1, y0, z0)), ((x0, y1, z0), (x1, y1, z0)),
            ((x0, y0, z1), (x1, y0, z1)), ((x0, y1, z1), (x1, y1, z1)),
            ((x0, y0, z0), (x0, y1, z0)), ((x1, y0, z0), (x1, y1, z0)),
            ((x0, y0, z1), (x0, y1, z1)), ((x1, y0, z1), (x1, y1, z1)),
            ((x0, y0, z0), (x0, y0, z1)), ((x1, y0, z0), (x1, y0, z1)),
            ((x0, y1, z0), (x0, y1, z1)), ((x1, y1, z0), (x1, y1, z1)),
        ]
        for (a, b) in edges:
            ax.plot(*zip(a, b), color="#8a8a8a", linewidth=0.8, linestyle="--", alpha=0.7)

    for i, title in enumerate(views.keys(), 1):
        ax = fig.add_subplot(plot_axes[i - 1], projection="3d")
        _draw_container_wireframe(ax, 0, 0, 0, x_max, y_max, z_max)
        for p in placements:
            y_center = (p["y"] + p["y_e"]) / 2
            orig = int(y_center // ROW_HEIGHT)
            orig = min(orig, NUM_ROWS - 1)
            new_row_index = band_remap[orig]
            if isinstance(views[title], int) and new_row_index != views[title]:
                continue
            if title in ("3D Overview", "Top View"):
                band_offset = band_new_y_start[orig]
                local_y_offset = p["y"] - (orig * ROW_HEIGHT)
                y_plot = band_offset + local_y_offset
                y_e_plot = y_plot + (p["y_e"] - p["y"])
            else:
                y_plot = p["y"]
                y_e_plot = p["y_e"]
            # Visual inset so adjacent same-colour items get a thin gap between them
            # (purely cosmetic — actual packing positions/extents are unchanged).
            _ix = min(25.0, max(5.0, (p["x_e"] - p["x"]) * 0.04))
            _iy = min(25.0, max(5.0, (y_e_plot - y_plot) * 0.04))
            _iz = min(15.0, max(3.0, (p["z_e"] - p["z"]) * 0.04))
            faces = cuboid_faces_from_extents(
                p["x"] + _ix, y_plot + _iy, p["z"] + _iz,
                p["x_e"] - _ix, y_e_plot - _iy, p["z_e"] - _iz,
            )
            color = row_colors.get(new_row_index, "gray")
            ax.add_collection3d(
                Poly3DCollection(
                    faces, facecolor=color, edgecolor="k", linewidth=0.6, alpha=0.55, zsort="average"
                )
            )
            cx = (p["x"] + p["x_e"]) / 2
            cy = (y_plot + y_e_plot) / 2
            cz = p["z_e"] - 350
            ax.text(
                cx, cy, cz,
                denote.get(p["item"], "?"),
                ha="center", va="center", fontsize=9, fontweight="bold", color="black",
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
        # Force a tick at the actual container length so the user can see
        # where the truck really ends (matplotlib otherwise stops at 12500
        # for a 13540 mm trailer, which makes legitimately-placed items
        # look like they're spilling out of the back).
        _step = 2500
        _ticks = list(range(0, int(x_max) + 1, _step))
        if _ticks[-1] != int(x_max):
            _ticks.append(int(x_max))
        ax.set_xticks(_ticks)

    ax = fig.add_subplot(distribution_slot)
    x_bins = compute_x_weight_bins(placements, 1000, 14000)
    xs, loads, allowed = [], [], []
    for x in range(0, int(np.ceil(float(x_max))), 1000):
        xs.append(x + 500)
        loads.append(x_bins.get(x, 0.0))
        allowed.append(allowed_weight_at_x(x + 500, chart))
    ax.plot(xs, allowed, label="Allowed Weight", color="red", linestyle="--")
    ax.plot(xs, loads, label="Occupied Weight", color="green", linestyle="--")
    ax.set_xlabel("Length (mm)")
    ax.set_ylabel("Weight (Kg)")
    ax.set_title("Distribution Curve")
    ax.legend()
    ax.grid(True)

    legend_text = "\n".join(
        f"{k} = {denote.get(k, '?')} : {assigned_items.get(k, 0)} in this truck"
        for k in selected_keys
    )
    legend_block = (
        f"Container type: {container_type}\n"
        f"{header_text}\n"
        + (f"{extra_legend_lines}\n" if extra_legend_lines else "")
        + "-------------------------------------------------------------\n"
        "Materials in this truck — symbol ↔ count\n"
        "-------------------------------------------------------------\n"
        f"{legend_text}\n"
        "-------------------------------------------------------------\n"
        "Container Statistics\n"
        "-------------------------------------------------------------\n"
        f"Load Weight: {weight:.2f} kg\n"
        f"Container Occupied Volume: {occ_volume_m3:.2f} m³\n"
        f"Container Remaining Volume: {remaining_volume_m3:.2f} m³\n"
        "-------------------------------------------------------------\n"
    )
    ax_legend = fig.add_subplot(legend_slot)
    ax_legend.axis("off")
    ax_legend.text(
        0.0, 1.0, legend_block,
        fontsize=10, va="top", ha="left", family="monospace",
        transform=ax_legend.transAxes,
    )
    return fig


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
            _is_multi = str(meta.get("mode", "")) == "multi"
            if _is_multi:
                _trucks = list(meta.get("trucks") or [])
                _bd = int(meta.get("backup_days", 0) or 0)
                st.caption(
                    f"Multi-truck run · **{len(_trucks)}** truck(s) · backup **{_bd}** day(s)"
                )
                if _trucks:
                    st.dataframe(
                        pd.DataFrame([
                            {
                                "Truck": t.get("index", i + 1),
                                "Anchor date": t.get("anchor_date", ""),
                                "Window end": t.get("window_end", ""),
                                "Items": t.get("item_count", 0),
                                "Weight (kg)": round(float(t.get("weight_kg", 0) or 0), 1),
                                "Fill (%)": round(float(t.get("fill_pct", 0) or 0), 1),
                            }
                            for i, t in enumerate(_trucks)
                        ]),
                        use_container_width=True,
                        hide_index=True,
                    )
                _unplc = list(meta.get("unplaceable") or [])
                if _unplc:
                    with st.expander(f"Unplaceable items ({len(_unplc)})", expanded=False):
                        st.dataframe(
                            pd.DataFrame(_unplc),
                            use_container_width=True,
                            hide_index=True,
                        )
                st.markdown("##### Open a truck")
                for i, t in enumerate(_trucks, start=1):
                    idx = int(t.get("index", i) or i)
                    title = (
                        f"Truck {idx} · {t.get('anchor_date', '—')} → ≤ {t.get('window_end', '—')} · "
                        f"{t.get('item_count', 0)} items · {float(t.get('weight_kg', 0) or 0):.0f} kg · "
                        f"fill {float(t.get('fill_pct', 0) or 0):.1f} %"
                    )
                    with st.expander(title, expanded=False):
                        png_t = storage.load_truck_plot(rid, idx) if _stor() else None
                        if png_t:
                            st.image(png_t, use_container_width=True)
                            _pdf_t = _png_bytes_to_pdf(png_t)
                            if _pdf_t:
                                st.download_button(
                                    f"Download truck {idx} (PDF)",
                                    _pdf_t,
                                    file_name=f"{meta.get('loading_name', 'run')}_truck_{idx:03d}.pdf",
                                    mime="application/pdf",
                                    key=f"hd_dl_pdf_{idx}",
                                )
                        else:
                            st.info("No plot stored for this truck.")
                        ai = t.get("assigned_items") or {}
                        if ai:
                            st.dataframe(
                                pd.DataFrame(
                                    sorted(ai.items(), key=lambda kv: -int(kv[1])),
                                    columns=["Material", "Count"],
                                ),
                                use_container_width=True,
                                hide_index=True,
                            )
            elif plot_png:
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
        _ITEM_SOURCE_LABELS = {
            "manual": "Manual entry (pick material + quantity)",
            "excel": "Excel file (e.g. ZMM_BS_AUSWERT_V2_CLS_AUTOLOAD…)",
            "catalog": "Full catalog (time.XLSX with Abholtermin → multi-truck)",
        }
        item_entry = st.radio(
            "Item source",
            options=["manual", "excel", "catalog"],
            format_func=lambda x: _ITEM_SOURCE_LABELS[x],
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
        elif item_entry == "excel":
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
        else:
            st.caption(
                "Catalog file: each row = one item with an **Abholtermin** (pickup date). "
                "Items are grouped by date and packed into one truck after another; a half-full "
                "truck is closed when the next item's date is outside the **backup-days** window."
            )
            st.number_input(
                "Backup days (window around the earliest date in each truck)",
                min_value=0,
                max_value=60,
                step=1,
                value=int(st.session_state.get("catalog_backup_days", 4) or 4),
                key="catalog_backup_days",
                help="Items are eligible for the same truck only if their date is within this many days of the truck's anchor date.",
            )
            f_catalog = st.file_uploader(
                "Catalog Excel (.xlsx) — e.g. time.XLSX",
                type=["xlsx"],
                key="catalog_xlsx_upload",
            )
            if st.button("Load catalog", key="btn_load_catalog"):
                if f_catalog is None:
                    st.error("Please choose a catalog Excel file first.")
                else:
                    try:
                        entries, no_date = parse_catalog_excel(io.BytesIO(f_catalog.getvalue()))
                        applied = [(k, d) for k, d in entries if k in ld_set]
                        unknown_keys = sorted({k for k, _ in entries if k not in ld_set})
                        unknown_rows = sum(1 for k, _ in entries if k not in ld_set)
                        st.session_state["catalog_items"] = applied
                        st.session_state["persist_catalog_xlsx"] = f_catalog.getvalue()
                        st.session_state["catalog_total_rows"] = len(entries) + len(no_date)
                        st.session_state["catalog_kept_rows"] = len(applied)
                        st.session_state["catalog_unknown_keys"] = unknown_keys
                        st.session_state["catalog_unknown_rows"] = unknown_rows
                        st.session_state["catalog_no_date_rows"] = len(no_date)
                        st.session_state.pop("_multi_result_cache", None)
                        st.session_state.pop("_multi_result_saved_once", None)
                        st.session_state.pop("_multi_loading_phase", None)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            cat = st.session_state.get("catalog_items") or []
            if cat:
                per_date = Counter(d for _, d in cat)
                _tot = int(st.session_state.get("catalog_total_rows", len(cat)) or len(cat))
                _kept = int(st.session_state.get("catalog_kept_rows", len(cat)) or len(cat))
                _unk_rows = int(st.session_state.get("catalog_unknown_rows", 0) or 0)
                _unk_keys = st.session_state.get("catalog_unknown_keys") or []
                _nodate = int(st.session_state.get("catalog_no_date_rows", 0) or 0)
                st.success(
                    f"Catalog: **{_kept} of {_tot}** rows kept · "
                    f"earliest **{min(per_date)}** · latest **{max(per_date)}** · "
                    f"**{len(per_date)}** distinct date(s)."
                )
                if _unk_rows or _nodate:
                    _msg = []
                    if _unk_rows:
                        _msg.append(
                            f"**{_unk_rows}** row(s) skipped — material not in the loaded "
                            f"material list (**{len(_unk_keys)}** distinct material number(s))"
                        )
                    if _nodate:
                        _msg.append(f"**{_nodate}** row(s) skipped — missing **Abholtermin**")
                    st.info(
                        " · ".join(_msg)
                        + f".  You can still click **Next** to optimize the **{_kept}** kept "
                        "row(s) into trucks, or go back to **← Materials setup** and import a "
                        "covering material Excel (e.g. **Materialübersicht.xlsx**) to include "
                        "the missing materials first."
                    )
                    if _unk_keys:
                        st.selectbox(
                            f"Materials in catalog but not in selected materials ({len(_unk_keys)})",
                            _unk_keys,
                            index=None,
                            placeholder=f"{len(_unk_keys)} missing material number(s) — open to browse",
                            key="catalog_unknown_browse",
                            help="These material numbers appear in the catalog but have no dimensions in the loaded material list, so they cannot be packed.",
                        )

    _cur_mode = st.session_state.get("item_entry_mode", "manual")
    c1, c2 = st.columns(2)
    with c1:
        if _cur_mode == "manual":
            if selected is not None and qty > 0:
                st.session_state["quantities"][selected] = qty
            elif selected in st.session_state["quantities"]:
                del st.session_state["quantities"][selected]
        st.markdown("###### Saved Quantities")
        st.write(f'Container : {st.session_state["container_selected"]} ')
        if _cur_mode == "catalog":
            cat = st.session_state.get("catalog_items") or []
            if cat:
                per_key = Counter(k for k, _ in cat)
                _tot = int(st.session_state.get("catalog_total_rows", len(cat)) or len(cat))
                _unk_rows = int(st.session_state.get("catalog_unknown_rows", 0) or 0)
                st.write(
                    f"Catalog: **{len(cat)} of {_tot}** rows · "
                    f"**{len(per_key)}** material(s) · "
                    f"backup **{int(st.session_state.get('catalog_backup_days', 4) or 4)}** day(s)"
                )
                if _unk_rows:
                    st.caption(
                        f"⚠ {_unk_rows} row(s) dropped because their material is not in the "
                        f"loaded material list — load **Materialübersicht.xlsx** on Materials setup "
                        f"to include them."
                    )
                for k, v in per_key.most_common():
                    st.write(f"- {k} : {v}")
            else:
                st.caption("No catalog loaded yet — pick **time.XLSX** above and **Load catalog**.")
        else:
            for k, v in st.session_state["quantities"].items():
                st.write(f"- {k} : {v}")
    _ld_chk = st.session_state.load_data
    _container_picked = st.session_state.get("container_selected")
    _need_meta = _materials_source_is_excel() and (
        not _meta_version_name() or not _meta_changer()
    )
    if _cur_mode == "catalog":
        _cat_kept = [(k, d) for k, d in (st.session_state.get("catalog_items") or []) if k in _ld_chk]
        _bad_keys = []
    else:
        _cat_kept = []
        _bad_keys = [k for k in st.session_state["quantities"] if k not in _ld_chk]

    _next_blocker: str | None = None
    if _cur_mode == "catalog":
        if not _cat_kept and _container_picked is None:
            _next_blocker = "both_catalog"
        elif not _cat_kept:
            _next_blocker = "catalog_empty"
        elif _container_picked is None:
            _next_blocker = "container"
        elif _need_meta:
            _next_blocker = "version_meta"
    else:
        if not st.session_state["quantities"] and _container_picked is None:
            _next_blocker = "both"
        elif not st.session_state["quantities"]:
            _next_blocker = "items"
        elif _container_picked is None:
            _next_blocker = "container"
        elif _bad_keys:
            _next_blocker = "unknown_mat"
        elif _need_meta:
            _next_blocker = "version_meta"

    warning_msg = {
        "items": "Please add items to the container to optimize…",
        "container": "Please select a **Container** at the top of this page to continue.",
        "both": "Please select a container and add items to optimize…",
        "unknown_mat": "Saved quantities include material numbers that are not in the load list. "
        "Use Material Excel import or remove those keys.",
        "version_meta": "**Version** and **changer** are required for **Excel** materials — "
        "set them on **← Materials setup**, then return here.",
        "catalog_empty": "Load a catalog file first (or none of its materials match the loaded material list).",
        "both_catalog": "Please select a container and **Load catalog** to optimize…",
    }

    with c2:
        c1_main,c2_main,_,_=st.columns([2,3,1,3])
        with c1_main:
            _next_clicked = st.button(
                "Next",
                key="nav_next",
                disabled=_next_blocker is not None,
                help=(warning_msg.get(_next_blocker) if _next_blocker else None),
            )
            if _next_clicked and _next_blocker is None:
                st.session_state.meta_container_selected = _container_picked
                if _cur_mode == "catalog":
                    st.session_state.pop("_multi_result_cache", None)
                    st.session_state.pop("_multi_result_saved_once", None)
                    st.session_state.pop("_multi_loading_phase", None)
                    st.session_state.page = "result_multi"
                else:
                    st.session_state.pop("_result_saved_once", None)
                    st.session_state.pop("_pack_result_cache", None)
                    st.session_state.page = "result"
                st.toast("Running optimization — this can take a minute for large catalogs.", icon="⏳")
                st.rerun()
        with c2_main:
            if st.button("Clear", key="c_clear"):
                st.session_state["quantities"].clear()
                st.session_state.pop("container_selected", None)
                st.session_state.pop("meta_container_selected", None)
                st.session_state.pop("_pack_result_cache", None)
                st.session_state.pop("catalog_items", None)
                st.session_state.pop("_multi_result_cache", None)
                st.session_state.pop("_multi_result_saved_once", None)
                st.session_state.pop("_multi_loading_phase", None)
                st.rerun()
        if _next_blocker is not None:
            st.warning(warning_msg[_next_blocker])


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

elif st.session_state.page == "result_multi":
    if _materials_source_is_excel() and (not _meta_version_name() or not _meta_changer()):
        st.subheader("Result — Full catalog (multi-truck)")
        st.error(
            "**Version** and **changer** are required for Excel-based materials — open "
            "**← Materials setup** and set both, then **Continue**."
        )
        st.stop()

    _ln = (st.session_state.get("loading_run_name") or "").strip()
    _on = (st.session_state.get("operator_name") or "").strip()
    _cn = _meta_client_name()
    _vn = _meta_version_name()
    _vch = _meta_changer()
    _backup = int(st.session_state.get("catalog_backup_days", 4) or 4)

    _ct = _meta_container_key()
    if not _ct or _ct not in container:
        st.subheader("Result — Full catalog (multi-truck)")
        st.error("No **container** stored for this result — go back to the tool, pick a container, then **Next**.")
        st.stop()

    ld = st.session_state.load_data
    fo = st.session_state.forbidden_on_data
    cat = [(k, d) for k, d in (st.session_state.get("catalog_items") or []) if k in ld]
    if not cat:
        st.subheader("Result — Full catalog (multi-truck)")
        st.error("No catalog items match the loaded materials. Reload **time.XLSX** and verify Materialnummer keys.")
        st.stop()

    cat_fp = hashlib.sha256(
        (
            json.dumps(sorted([(k, d.isoformat()) for k, d in cat]))
            + f"|{_ct}|{_backup}|"
            + json.dumps({k: ld[k] for k in sorted({k for k, _ in cat})}, sort_keys=True, default=str)
            + json.dumps({k: sorted(v) for k, v in fo.items()}, sort_keys=True)
        ).encode("utf-8")
    ).hexdigest()

    cache = st.session_state.get("_multi_result_cache")
    if not (isinstance(cache, dict) and cache.get("fp") == cat_fp):
        # ----- Plain full-page loading sheet (nothing else is rendered) -----
        # All loading content lives inside ONE st.empty() container at delta
        # position 0.  We then flush positions 1..N with empty placeholders so
        # every old widget that the previous page (tool / result) rendered is
        # explicitly replaced *before* the multi-second `pack_multi_trucks`
        # call starts.  Without this, Streamlit only clears unmatched DOM
        # positions when the script ends — meaning all the trailing tool-page
        # widgets stay visible behind the loading sheet for the entire pack.
        loading_root = st.empty()
        with loading_root.container():
            st.markdown(
                """
                <style>
                  [data-testid="stSidebar"], [data-testid="stLogo"] {display: none !important;}
                  #schnellecke-header {display: none !important;}
                  header[data-testid="stHeader"] {background: #ffffff !important; z-index: 100000 !important;}
                  [data-testid="stToastContainer"] {display: none !important;}
                  html, body, .stApp,
                  [data-testid="stAppViewContainer"],
                  section[data-testid="stMain"],
                  section[data-testid="stMain"] > div,
                  section[data-testid="stMain"] > div > div {
                    background: #ffffff !important;
                    background-color: #ffffff !important;
                  }
                  .stApp {min-height: 100vh !important;}
                  .block-container {
                    background: #ffffff !important;
                    min-height: calc(100vh - 60px) !important;
                    padding-top: 8vh !important;
                    padding-bottom: 6vh !important;
                    max-width: 720px !important;
                    margin: 0 auto !important;
                    position: relative;
                    z-index: 99999;
                  }
                </style>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div style='text-align:center;padding-top:4vh;'>"
                "<h1 style='margin-bottom:0.25rem;'>Optimizing your load</h1>"
                f"<p style='color:#6b7280;margin-top:0;'>Packing {len(cat)} catalog items into trucks. "
                "This can take a minute for large catalogs — please don't close the tab.</p>"
                "</div>",
                unsafe_allow_html=True,
            )
            pack_progress = st.progress(0, text="Starting bin packing…")
            stage_caption = st.empty()
            stage_caption.caption("Preparing items by Abholtermin window…")

        # Flush every remaining DOM position from the previous page (tool page
        # has ~30 widgets).  Each `st.empty()` claims a delta slot; with
        # nothing put inside, it renders as an invisible placeholder, which
        # forces Streamlit to remove whatever the *previous* run had at that
        # slot — even though our heavy compute below keeps the script running
        # for many seconds.
        flush_slots = [st.empty() for _ in range(64)]

        # Two-phase render: first hit just paints the overlay + flushes, then
        # reruns so Streamlit fully commits the new (mostly-empty) DOM before
        # we sit on the CPU for `pack_multi_trucks`.
        if st.session_state.get("_multi_loading_phase") != "compute":
            st.session_state["_multi_loading_phase"] = "compute"
            st.rerun()

        def _on_pack_progress(stage, done, total, detail):
            pct = 0 if total <= 0 else min(100, int(round(done * 100 / total)))
            # Reserve 80 % of the bar for packing; figure rendering uses the rest.
            pack_progress.progress(
                min(80, int(pct * 0.8)),
                text=f"Packing {done} / {total} items",
            )
            stage_caption.caption(
                f"{'Consolidating' if stage == 'consolidate' else 'Packing'} · {detail}"
            )

        dated_items = [(k, ld[k], d) for k, d in cat]
        trucks, unplaceable = pack_multi_trucks(
            _ct, dated_items, _backup, chart, fo, progress=_on_pack_progress
        )

        all_keys = sorted({k for k, _ in cat})
        denote = {k: _legend_symbol(i) for i, k in enumerate(all_keys)}

        cont_def = container[_ct]
        cont_vol_m3 = (cont_def["length"] * cont_def["width"] * cont_def["height"]) / 1e9

        truck_figures: list[bytes] = []
        truck_pdfs: list[bytes] = []
        trucks_meta_serializable: list[dict] = []
        total_trucks = max(1, len(trucks))
        stage_caption.caption(f"Rendering {total_trucks} truck plot(s)…")
        for idx, t in enumerate(trucks, start=1):
            pack_progress.progress(
                80 + int(20 * (idx - 1) / total_trucks),
                text=f"Rendering truck {idx} of {total_trucks}…",
            )
            assigned = Counter(p["item"] for p in t["placements"])
            keys_here = [k for k in all_keys if assigned.get(k, 0) > 0]
            occ = float(t["fill_volume_m3"])
            rem = max(0.0, cont_vol_m3 - occ)
            header_text = (
                f"Truck {idx} — Anchor {t['anchor_date']} · Window ≤ {t['window_end']} · "
                f"{sum(assigned.values())} items · Fill {t['fill_pct']:.1f}% · "
                f"Loading: {_ln or '—'} · Client: {_cn or '—'}"
            )
            extra = (
                f"Earliest date: {min(d for _, d in t['items_dates']) if t['items_dates'] else '—'}  ·  "
                f"Latest date: {max(d for _, d in t['items_dates']) if t['items_dates'] else '—'}"
            )
            fig = _build_truck_figure(
                container_type=_ct,
                placements=t["placements"],
                selected_keys=keys_here,
                denote=denote,
                weight=float(t["weight_kg"]),
                occ_volume_m3=occ,
                remaining_volume_m3=rem,
                assigned_items=dict(assigned),
                header_text=header_text,
                extra_legend_lines=extra,
            )
            png_buf = io.BytesIO()
            fig.savefig(png_buf, format="png", dpi=120, bbox_inches="tight")
            truck_figures.append(png_buf.getvalue())
            try:
                pdf_buf = io.BytesIO()
                fig.savefig(pdf_buf, format="pdf", bbox_inches="tight")
                truck_pdfs.append(pdf_buf.getvalue())
            except Exception:
                truck_pdfs.append(b"")
            plt.close(fig)

            trucks_meta_serializable.append({
                "index": idx,
                "anchor_date": t["anchor_date"].isoformat(),
                "window_end": t["window_end"].isoformat(),
                "container_type": t["container_type"],
                "weight_kg": float(t["weight_kg"]),
                "fill_volume_m3": occ,
                "fill_pct": float(t["fill_pct"]),
                "item_count": int(sum(assigned.values())),
                "assigned_items": {str(k): int(v) for k, v in assigned.items()},
                "items_dates": [(str(k), d.isoformat()) for k, d in t["items_dates"]],
            })

        cache = {
            "fp": cat_fp,
            "container_type": _ct,
            "backup_days": _backup,
            "trucks": trucks,
            "trucks_meta": trucks_meta_serializable,
            "denote": denote,
            "all_keys": all_keys,
            "unplaceable": [(str(k), d.isoformat()) for k, d in unplaceable],
            "truck_pngs": truck_figures,
            "truck_pdfs": truck_pdfs,
            "total_items": len(cat),
        }
        st.session_state["_multi_result_cache"] = cache
        st.session_state.pop("_multi_loading_phase", None)

        pack_progress.progress(
            100,
            text=f"Done — {len(trucks)} truck(s), "
            f"{sum(t['item_count'] for t in trucks_meta_serializable)} items placed.",
        )
        stage_caption.caption("Loading the result page…")
        st.rerun()

    # ===== Result UI (renders only after the loading sheet has cached results) =====
    st.subheader("Result — Full catalog (multi-truck)")
    st.caption(
        f"**Loading:** {_ln or '—'} · **Operator:** {_on or '—'} · "
        f"**Client:** {_cn or '—'} · **Version:** {_vn or '—'} · "
        f"**Changer:** {_vch or '—'} · **Backup days:** {_backup}"
    )

    nb1, nb2, nb3 = st.columns(3)
    with nb1:
        if st.button("← Back to tool", key="resm_tool"):
            st.session_state.pop("_multi_result_cache", None)
            st.session_state.pop("_multi_loading_phase", None)
            st.session_state.page = "tool"
            st.rerun()
    with nb2:
        if st.button("← Home", key="resm_home"):
            st.session_state.pop("_multi_result_cache", None)
            st.session_state.pop("_multi_loading_phase", None)
            st.session_state.page = "home"
            st.rerun()
    with nb3:
        if st.button("Re-run optimization", key="resm_rerun"):
            st.session_state.pop("_multi_result_cache", None)
            st.session_state.pop("_multi_loading_phase", None)
            st.session_state.pop("_multi_result_saved_once", None)
            st.rerun()

    trucks_meta_serializable = cache["trucks_meta"]
    truck_figures = cache["truck_pngs"]
    truck_pdfs = cache["truck_pdfs"]
    unplaceable_iso = cache["unplaceable"]

    total_items = cache["total_items"]
    placed_total = sum(t["item_count"] for t in trucks_meta_serializable)
    unplaced_total = len(unplaceable_iso)
    avg_fill = (
        sum(t["fill_pct"] for t in trucks_meta_serializable) / max(1, len(trucks_meta_serializable))
    )

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Trucks", len(trucks_meta_serializable))
    s2.metric("Items placed", f"{placed_total} / {total_items}")
    s3.metric("Unplaceable", unplaced_total)
    s4.metric("Avg fill", f"{avg_fill:.1f} %")

    if trucks_meta_serializable:
        rows = [
            {
                "Truck": t["index"],
                "Anchor date": t["anchor_date"],
                "Window end": t["window_end"],
                "Items": t["item_count"],
                "Weight (kg)": round(t["weight_kg"], 1),
                "Fill (%)": round(t["fill_pct"], 1),
                "Container": t["container_type"],
            }
            for t in trucks_meta_serializable
        ]
        st.markdown("##### Trucks")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if unplaceable_iso:
        with st.expander(f"Unplaceable items ({len(unplaceable_iso)})", expanded=False):
            udf = pd.DataFrame(unplaceable_iso, columns=["Material", "Abholtermin"])
            st.dataframe(udf, use_container_width=True, hide_index=True)

    if not st.session_state.get("_multi_result_saved_once"):
        if _stor():
            try:
                quantities_total = {
                    str(k): int(v) for k, v in Counter(k for k, _ in cat).items()
                }
                rid = storage.save_run_multi(
                    client=_meta_client_name() or "unknown",
                    loading_name=_ln,
                    operator_name=_on,
                    version_name=_meta_version_name(),
                    changer=_meta_changer(),
                    container_type=str(_ct),
                    backup_days=_backup,
                    quantities=quantities_total,
                    load_data=st.session_state.load_data,
                    forbidden_on=st.session_state.forbidden_on_data,
                    trucks_meta=trucks_meta_serializable,
                    truck_plots_png=truck_figures,
                    unplaceable=[
                        {"material": k, "abholtermin": d}
                        for k, d in unplaceable_iso
                    ],
                    material_xlsx=st.session_state.get("persist_material_xlsx"),
                    stacking_xlsx=st.session_state.get("persist_stacking_xlsx"),
                    catalog_xlsx=st.session_state.get("persist_catalog_xlsx"),
                    summary_plot_png=truck_figures[0] if truck_figures else None,
                )
                if rid:
                    st.success(f"Saved to MinIO as one history entry ({len(truck_figures)} truck plots).")
            except Exception as e:
                st.warning(f"Could not save to MinIO: {e}")
        elif storage is not None and storage.storage_enabled() and not storage.minio_available():
            st.info(
                "MinIO save skipped: install **minio** (`pip install minio`). "
                "Per-truck PDFs are still available below."
            )
        st.session_state._multi_result_saved_once = True

    _slug = _safe_filename_part(_cn or "")
    _ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    st.markdown("##### Open a truck")
    for tmeta, png, pdf in zip(trucks_meta_serializable, truck_figures, truck_pdfs):
        title = (
            f"Truck {tmeta['index']} · {tmeta['anchor_date']} → ≤ {tmeta['window_end']} · "
            f"{tmeta['item_count']} items · {tmeta['weight_kg']:.0f} kg · "
            f"fill {tmeta['fill_pct']:.1f} %"
        )
        with st.expander(title, expanded=False):
            st.image(png, use_container_width=True)
            if tmeta["assigned_items"]:
                _items_df = pd.DataFrame(
                    sorted(tmeta["assigned_items"].items(), key=lambda kv: -kv[1]),
                    columns=["Material", "Count"],
                )
                st.dataframe(_items_df, use_container_width=True, hide_index=True)
            if pdf:
                st.download_button(
                    f"Download truck {tmeta['index']} (PDF)",
                    pdf,
                    file_name=f"{_ts}_{_slug}_truck_{tmeta['index']:03d}.pdf",
                    mime="application/pdf",
                    key=f"resm_dl_pdf_{tmeta['index']}",
                )
