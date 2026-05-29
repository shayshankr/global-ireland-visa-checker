import re
import requests
import pandas as pd
from io import BytesIO
from bs4 import BeautifulSoup
import pdfplumber

from cache import (
    load_from_disk, save_to_disk, is_cache_fresh,
    check_etag, etag_unchanged
)

# ── easyocr singleton — initialised at module import time ─────────────────────
# easyocr downloads a ~70 MB model on first use.  Initialising it inside
# ThreadPoolExecutor threads causes the download to happen simultaneously
# across multiple threads which breaks silently.  We init once here, at import
# time (before any threads start), so every thread reuses the same reader.
_ocr_reader = None
try:
    import easyocr as _easyocr_mod
    _ocr_reader = _easyocr_mod.Reader(['en'], gpu=False, verbose=False)
except Exception:
    _ocr_reader = None  # OCR unavailable; PDF embassies will skip scanned files


def _get_ocr_reader():
    return _ocr_reader

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )
}


def _get_with_retry(url: str, timeout: int = 30, retries: int = 2) -> requests.Response:
    """GET with retry on timeout/connection error."""
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt == retries:
                raise
            continue


def _find_file_links(page_url: str, keyword: str, file_ext: str) -> list[dict]:
    """Scrape a page and return all matching file links with their labels."""
    response = _get_with_retry(page_url, timeout=30, retries=2)
    soup = BeautifulSoup(response.content, "html.parser")

    links = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if href.lower().endswith(file_ext) and keyword.lower() in text.lower():
            full_url = href if href.startswith("http") else requests.compat.urljoin(page_url, href)
            clean_label = re.sub(r'(ods|pdf)[\d\.\s]+\w*$', '', text, flags=re.IGNORECASE).strip()
            links.append({"label": clean_label, "url": full_url})
    return links


def _parse_ods(content: bytes) -> pd.DataFrame:
    """Parse an ODS spreadsheet and return Application Number + Decision rows."""
    raw = pd.read_excel(BytesIO(content), engine="odf", header=None)

    header_row = None
    for i, row in raw.iterrows():
        vals = [str(v).lower() for v in row.values]
        if any("application number" in v for v in vals):
            header_row = i
            break

    if header_row is None:
        raise ValueError("Could not locate 'Application Number' header in ODS file.")

    df = raw.iloc[header_row + 1:].copy()
    df = df.iloc[:, 2:4].copy()
    df.columns = ["Application Number", "Decision"]
    df.dropna(how="all", inplace=True)
    df = df[df["Application Number"].astype(str).str.strip().str.lower() != "application number"]
    df.reset_index(drop=True, inplace=True)
    df["Application Number"] = df["Application Number"].astype(str).str.strip()
    df["Decision"] = df["Decision"].astype(str).str.strip()
    return df


def _parse_pdf(content: bytes) -> pd.DataFrame:
    """Parse a PDF — text extraction first, OCR fallback for scanned/image PDFs."""
    rows = []

    # ── Attempt 1: pdfplumber table extraction (text-based PDFs) ──────────────
    with pdfplumber.open(BytesIO(content)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not row or len(row) < 2:
                        continue
                    app_num = str(row[0]).strip() if row[0] else ""
                    decision = str(row[1]).strip() if row[1] else ""
                    if app_num.lower() in ("application number", "", "none"):
                        continue
                    if decision.lower() in ("decision", "", "none"):
                        continue
                    rows.append({"Application Number": app_num, "Decision": decision})

    if rows:
        return pd.DataFrame(rows)

    # ── Attempt 2: easyocr fallback for image/scanned PDFs ───────────────────
    try:
        import fitz
        import numpy as np

        reader = _get_ocr_reader()   # thread-safe singleton — no parallel re-init
        doc = fitz.open(stream=content, filetype="pdf")
        for page in doc:
            mat = fitz.Matrix(2.0, 2.0)
            # Force RGB (3 channels) — avoids RGBA shape mismatch on some builds
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            results = reader.readtext(img_array, detail=0, paragraph=False)
            texts = [t.strip() for t in results]
            for i, text in enumerate(texts):
                if re.match(r'^\d{7,9}$', text) and i + 1 < len(texts):
                    decision = texts[i + 1].strip()
                    if re.match(r'^(Approved|Refused|Granted|Rejected)$', decision, re.IGNORECASE):
                        rows.append({
                            "Application Number": text,
                            "Decision": decision.capitalize()
                        })
    except Exception:
        pass

    return pd.DataFrame(rows)


def fetch_embassy(embassy: dict) -> dict:
    """
    Fetch data for a single embassy with 3-layer caching:
      1. Disk cache fresh?        → return disk data instantly
      2. ETag unchanged?          → refresh timestamp, return disk data
      3. File URL changed/new?    → download, parse, save to disk

    Returns:
        {
            "name":        str,
            "status":      "ok" | "error",
            "df":          pd.DataFrame | None,
            "reports":     list[str],
            "error":       str | None,
            "cache_status": "disk_fresh" | "etag_match" | "fetched" | "error"
        }
    """
    name = embassy["name"]
    result = {
        "name": name, "status": "error", "df": None,
        "reports": [], "error": None, "cache_status": "error"
    }

    try:
        # ── Step 1: Find the latest file URL from the source page ──────────────
        links = _find_file_links(embassy["url"], embassy["keyword"], embassy["file_ext"])
        if not links:
            result["error"] = f"No {embassy['file_ext'].upper()} files found on page."
            return result

        latest_url = links[0]["url"]
        latest_label = links[0]["label"]

        # ── Step 2: Check disk cache ───────────────────────────────────────────
        cached_df, cached_meta = load_from_disk(name)

        if cached_df is not None and cached_meta is not None:
            # Cache is fresh (< 24h) AND same file URL → return immediately
            if is_cache_fresh(cached_meta) and cached_meta.get("file_url") == latest_url:
                result.update({
                    "status": "ok",
                    "df": cached_df,
                    "reports": cached_meta.get("reports", [latest_label]),
                    "cache_status": "disk_fresh",
                })
                return result

            # Cache exists but may be stale → check ETag before re-downloading
            new_etag, new_last_modified = check_etag(latest_url)
            if etag_unchanged(cached_meta, new_etag, new_last_modified):
                # File hasn't changed on server — refresh timestamp, return cached
                save_to_disk(name, cached_df, latest_url, new_etag,
                             new_last_modified, cached_meta.get("reports", []))
                result.update({
                    "status": "ok",
                    "df": cached_df,
                    "reports": cached_meta.get("reports", [latest_label]),
                    "cache_status": "etag_match",
                })
                return result

        # ── Step 3: Download fresh data ────────────────────────────────────────
        frames = []
        report_labels = []
        parsed_url = latest_url  # will be updated to the actually-parsed file URL
        etag = None
        last_modified = None
        for item in links:
            try:
                r = _get_with_retry(item["url"], timeout=60, retries=2)
                item_etag = r.headers.get("ETag")
                item_last_modified = r.headers.get("Last-Modified")

                df_part = _parse_ods(r.content) if embassy["type"] == "ods" else _parse_pdf(r.content)

                if not df_part.empty:
                    df_part["Source"] = name
                    df_part["Report"] = item["label"]
                    frames.append(df_part)
                    report_labels.append(item["label"])
                    # Track the URL we actually parsed (not necessarily the newest)
                    parsed_url = item["url"]
                    etag = item_etag
                    last_modified = item_last_modified
                    # For PDFs: stop at first parseable file (skip scanned/image PDFs)
                    if embassy["type"] == "pdf":
                        break
            except Exception as e:
                report_labels.append(f"⚠️ {item['label']} — failed: {e}")

        if not frames:
            result["error"] = "All files failed to parse."
            return result

        combined = pd.concat(frames, ignore_index=True)
        combined.drop_duplicates(subset=["Application Number"], keep="last", inplace=True)
        combined.reset_index(drop=True, inplace=True)

        # Save to disk — use parsed_url (the file we actually read), not latest_url.
        # This ensures next run sees a URL mismatch if a newer file is published.
        save_to_disk(name, combined, parsed_url, etag, last_modified, report_labels)

        result.update({
            "status": "ok",
            "df": combined,
            "reports": report_labels,
            "cache_status": "fetched",
        })

    except requests.RequestException as e:
        # Network failed — try returning stale disk cache as fallback
        cached_df, cached_meta = load_from_disk(name)
        if cached_df is not None:
            result.update({
                "status": "ok",
                "df": cached_df,
                "reports": cached_meta.get("reports", ["⚠️ Stale cache (network error)"]),
                "cache_status": "stale_fallback",
                "error": None,
            })
        else:
            result["error"] = f"Network error: {e}"
    except Exception as e:
        result["error"] = str(e)

    return result
