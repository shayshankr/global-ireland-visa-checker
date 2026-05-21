import re
import pandas as pd
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

from embassies import EMBASSIES
from fetchers import fetch_embassy

st.set_page_config(
    page_title="Ireland Visa Decision Checker",
    page_icon="🇮🇪",
    layout="centered",
)


# ── Input validation ──────────────────────────────────────────────────────────

def normalize_app_number(value: str) -> str:
    return value.strip().upper().removeprefix("IRL")


def validate_input(raw: str) -> tuple[bool, str, str]:
    raw = raw.strip()
    if not raw:
        return False, "", ""

    upper = raw.upper()

    if not re.match(r'^[A-Za-z0-9]+$', raw):
        return False, "❌ No spaces or special characters allowed. Use format: `IRL12345678` or `12345678`", ""

    if upper.startswith("IRL"):
        numeric_part = raw[3:]
        if not numeric_part.isdigit():
            return False, "❌ After `IRL` only digits are allowed. Example: `IRL63690452`", ""
    else:
        if not raw.isdigit():
            letters_found = "".join(sorted(set(c for c in upper if c.isalpha())))
            if upper[-1].isalpha():
                return False, f"❌ Letters must come at the **start** as `IRL` prefix only. Found `{letters_found}` at end.", ""
            return False, f"❌ Only the prefix `IRL` is allowed. Found unexpected letters: `{letters_found}`.", ""
        numeric_part = raw

    if len(numeric_part) < 8:
        return False, f"❌ Too short ({len(numeric_part)} digits). Must be exactly **8 digits**.", ""
    if len(numeric_part) > 8:
        return False, f"❌ Too long ({len(numeric_part)} digits). Must be exactly **8 digits**.", ""

    return True, "", numeric_part


# ── HTML table helpers ────────────────────────────────────────────────────────

def decision_badge(decision_val: str) -> str:
    if "approv" in decision_val.lower() or "grant" in decision_val.lower():
        return f'<span style="color:#1e7e34;font-weight:600">{decision_val}</span>'
    elif "refus" in decision_val.lower() or "reject" in decision_val.lower():
        return f'<span style="color:#c0392b;font-weight:600">{decision_val}</span>'
    return decision_val


def html_nearest_table(dataframe: pd.DataFrame) -> str:
    rows = ""
    for _, row in dataframe.iterrows():
        rows += (
            f"<tr>"
            f"<td style='padding:6px'>{row['Nearest Application']}</td>"
            f"<td style='padding:6px;text-align:right'>{row['Application Number']}</td>"
            f"<td style='padding:6px'>{decision_badge(str(row['Decision']))}</td>"
            f"<td style='padding:6px'>{row['Source']}</td>"
            f"<td style='padding:6px;text-align:right'>{row['Difference']}</td>"
            f"</tr>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:14px'>"
        "<thead><tr style='border-bottom:2px solid #ddd'>"
        "<th style='text-align:left;padding:6px'>Position</th>"
        "<th style='text-align:right;padding:6px'>Application Number</th>"
        "<th style='text-align:left;padding:6px'>Decision</th>"
        "<th style='text-align:left;padding:6px'>Embassy</th>"
        "<th style='text-align:right;padding:6px'>Difference</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_all_embassies() -> dict:
    """
    Fetch all embassies in parallel using ThreadPoolExecutor.
    Returns dict keyed by embassy name:
      { "New Delhi": { status, df, reports, error }, ... }
    """
    results = {}
    with ThreadPoolExecutor(max_workers=len(EMBASSIES)) as executor:
        future_to_name = {
            executor.submit(fetch_embassy, embassy): embassy["name"]
            for embassy in EMBASSIES
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as e:
                results[name] = {
                    "name": name,
                    "status": "error",
                    "df": None,
                    "reports": [],
                    "error": str(e),
                }
    return results


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("🇮🇪 Ireland Visa Decision Checker")
st.caption("All Embassies · Data sourced from ireland.ie")

# ── How to use ────────────────────────────────────────────────────────────────
with st.expander("ℹ️ How to use this tool"):
    st.markdown("""
    1. Enter your 8-digit application number like `83276171` or with prefix `IRL83276171`
    2. Get instant status check across all embassies — New Delhi, Beijing, Abuja, Abu Dhabi, Ankara.
    3. See nearest processed numbers if yours isn't found.
    4. Please share with your family and friends this application.
    5. More than 4130+ people have used this application as of April 2026. Last week usage 200 people.
    6. Contact the developer if any issues while using this application.
    7. #irelandvisaresult #ireland #AIforgood #studentinireland #irelandeducation #NCIcollege #NCI
    """)

# ── Error fallback ────────────────────────────────────────────────────────────
with st.expander("⚠️ If any error click on me"):
    st.markdown("""
    1. Visit the [original website](https://www.ireland.ie) and check your embassy page directly.
    2. Mostly the error is due to the file not being available on the server.
       Once the embassy website has the file, this application will work.
    3. Try the individual embassy apps if one embassy is causing issues.
    """)

with st.spinner("Loading visa decisions from all embassies…"):
    all_data = load_all_embassies()

# ── Embassy status panel ──────────────────────────────────────────────────────
st.subheader("Embassy Status")
cols = st.columns(len(EMBASSIES))
for col, embassy in zip(cols, EMBASSIES):
    result = all_data[embassy["name"]]
    freq = embassy.get("update_frequency", "")
    if result["status"] == "ok":
        count = len(result["df"])
        col.metric(embassy["name"], f"{count:,}", f"✅ {freq}")
    else:
        col.metric(embassy["name"], "❌ Error", freq)

# Show errors in expander
errors = {name: r for name, r in all_data.items() if r["status"] == "error"}
if errors:
    with st.expander(f"⚠️ {len(errors)} embassy error(s) — click to see details"):
        for name, r in errors.items():
            st.error(f"**{name}:** {r['error']}")

# Show loaded reports per embassy
with st.expander("📋 Reports loaded per embassy"):
    for name, r in all_data.items():
        if r["status"] == "ok":
            st.markdown(f"**{name}**")
            for label in r["reports"]:
                st.write(f"  • {label}")

# ── Build combined dataframe ──────────────────────────────────────────────────
ok_frames = [r["df"] for r in all_data.values() if r["status"] == "ok" and r["df"] is not None]

if not ok_frames:
    st.error("No embassy data could be loaded. Please try again later.")
    st.stop()

df_all = pd.concat(ok_frames, ignore_index=True)

# ── Combined stats ────────────────────────────────────────────────────────────
st.divider()
st.subheader("Combined Statistics")
total = len(df_all)
approved = df_all["Decision"].str.lower().str.contains("approv|grant").sum()
refused = df_all["Decision"].str.lower().str.contains("refus|reject").sum()

col1, col2, col3 = st.columns(3)
col1.metric("Total Decisions", f"{total:,}")
col2.metric("Approved", f"{int(approved):,}")
col3.metric("Refused", f"{int(refused):,}")

st.divider()

# ── Search ────────────────────────────────────────────────────────────────────
st.subheader("Check your application")
st.caption("Searches across all embassies · `63690452` · `IRL63690452` · `irl63690452`")

query = st.text_input(
    "Enter your Application Number",
    placeholder="e.g. IRL63690452 or 63690452",
    max_chars=11,
).strip()

if query:
    is_valid, error_msg, normalized_query = validate_input(query)

    if not is_valid:
        st.error(error_msg)
    else:
        df_norm = df_all["Application Number"].apply(normalize_app_number)
        result = df_all[df_norm == normalized_query]

        if result.empty:
            st.warning(f"No record found for **{normalized_query}** across all embassies.")

            # Nearest numbers across all data
            try:
                query_int = int(normalized_query)
                nums = df_all["Application Number"].apply(
                    lambda x: int(normalize_app_number(x)) if normalize_app_number(x).isdigit() else None
                ).dropna().astype(int)

                below = nums[nums < query_int]
                above = nums[nums > query_int]

                nearest_rows = []
                if not below.empty:
                    idx = below.idxmax()
                    row = df_all.loc[idx]
                    nearest_rows.append({
                        "Nearest Application": "Before",
                        "Application Number": str(row["Application Number"]),
                        "Decision": row["Decision"],
                        "Source": row["Source"],
                        "Difference": query_int - below.max(),
                    })
                if not above.empty:
                    idx = above.idxmin()
                    row = df_all.loc[idx]
                    nearest_rows.append({
                        "Nearest Application": "After",
                        "Application Number": str(row["Application Number"]),
                        "Decision": row["Decision"],
                        "Source": row["Source"],
                        "Difference": above.min() - query_int,
                    })

                if nearest_rows:
                    st.subheader("Nearest Application Numbers")
                    nearest_df = pd.DataFrame(nearest_rows)
                    st.markdown(html_nearest_table(nearest_df), unsafe_allow_html=True)

            except ValueError:
                pass

        else:
            row = result.iloc[0]
            decision = row["Decision"]
            app_num = row["Application Number"]
            source = row["Source"]
            report = row["Report"]

            msg = f"**Application {app_num} — {decision}**"
            sub = f"📍 Found in **{source}** · 📄 Report: *{report}*"

            if "approv" in decision.lower() or "grant" in decision.lower():
                st.success(f"{msg} ✅")
            elif "refus" in decision.lower() or "reject" in decision.lower():
                st.error(f"{msg} ❌")
            else:
                st.info(f"{msg}")

            st.caption(sub)

st.divider()

# ── Per-embassy breakdown ─────────────────────────────────────────────────────
with st.expander("📊 Per-embassy breakdown"):
    rows_html = ""
    for name, r in all_data.items():
        if r["status"] == "ok":
            counts = r["df"]["Decision"].value_counts()
            approved_c = int(counts.get("Approved", counts.get("Granted", 0)))
            refused_c = int(counts.get("Refused", counts.get("Rejected", 0)))
            total_c = len(r["df"])
            rows_html += (
                f"<tr>"
                f"<td style='padding:8px;font-weight:600'>{name}</td>"
                f"<td style='padding:8px;text-align:center'>{total_c:,}</td>"
                f"<td style='padding:8px;text-align:center;color:#1e7e34;font-weight:600'>{approved_c:,}</td>"
                f"<td style='padding:8px;text-align:center;color:#c0392b;font-weight:600'>{refused_c:,}</td>"
                f"<td style='padding:8px;text-align:center'>✅</td>"
                f"</tr>"
            )
        else:
            rows_html += (
                f"<tr>"
                f"<td style='padding:8px;font-weight:600'>{name}</td>"
                f"<td colspan='3' style='padding:8px;color:#c0392b'>{r['error']}</td>"
                f"<td style='padding:8px;text-align:center'>❌</td>"
                f"</tr>"
            )

    st.markdown(
        "<table style='width:100%;border-collapse:collapse;font-size:14px'>"
        "<thead><tr style='border-bottom:2px solid #ddd'>"
        "<th style='text-align:left;padding:8px'>Embassy</th>"
        "<th style='text-align:center;padding:8px'>Total</th>"
        "<th style='text-align:center;padding:8px'>Approved</th>"
        "<th style='text-align:center;padding:8px'>Refused</th>"
        "<th style='text-align:center;padding:8px'>Status</th>"
        f"</tr></thead><tbody>{rows_html}</tbody></table>",
        unsafe_allow_html=True,
    )

# ── Download ──────────────────────────────────────────────────────────────────
st.divider()
csv = df_all.to_csv(index=False).encode("utf-8")
st.download_button(
    label="⬇️ Download combined dataset (CSV)",
    data=csv,
    file_name="ireland_visa_decisions_all.csv",
    mime="text/csv",
)

st.caption("Data refreshes every hour · Sources: ireland.ie")
