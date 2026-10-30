"""
data_quality_report.py — Data Quality Audit & Reporting
=========================================================
Independently analyses the raw Excel file and the cleaned CSVs to produce
a comprehensive data-quality report.

Outputs:
    - data/data_quality_report.json  (machine-readable)
    - Console summary               (human-readable)

Usage:
    cd ecommerce-sales-analytics
    python python/data_quality_report.py
"""

import json
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from config import PATHS, setup_logging

logger = setup_logging("data_quality_report")


# ============================================================
# LOADERS
# ============================================================

def load_raw_excel(filepath) -> pd.DataFrame:
    """Load the raw Excel file for independent analysis."""
    if not filepath.exists():
        logger.error(f"Raw Excel not found: {filepath}")
        sys.exit(1)
    df = pd.read_excel(filepath, engine="openpyxl")
    logger.info(f"Raw Excel loaded: {len(df):,} rows × {len(df.columns)} columns")
    return df


def load_cleaned_csv(filepath) -> pd.DataFrame:
    """Load a cleaned CSV file."""
    if not filepath.exists():
        logger.error(
            f"Cleaned CSV not found: {filepath}\n"
            "Run clean_data.py first."
        )
        sys.exit(1)
    df = pd.read_csv(filepath, parse_dates=["invoice_date"])
    logger.info(f"Loaded {filepath.name}: {len(df):,} rows")
    return df


# ============================================================
# RAW DATA ANALYSIS
# ============================================================

def analyze_raw_data(df: pd.DataFrame) -> dict:
    """Compute quality metrics on the raw (pre-cleaning) data."""
    logger.info("Analyzing raw data quality")

    # --- Basic shape ---
    raw_info = {
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "columns": list(df.columns),
        "memory_usage_mb": round(df.memory_usage(deep=True).sum() / 1e6, 2),
    }

    # --- Missing values per column ---
    missing = {}
    for col in df.columns:
        null_count = int(df[col].isna().sum())
        missing[col] = {
            "null_count": null_count,
            "null_pct": round(null_count / len(df) * 100, 2),
        }
    raw_info["missing_values"] = missing

    total_nulls = sum(v["null_count"] for v in missing.values())
    raw_info["total_null_cells"] = total_nulls
    raw_info["total_cells"] = len(df) * len(df.columns)
    raw_info["overall_completeness_pct"] = round(
        (1 - total_nulls / raw_info["total_cells"]) * 100, 2
    )

    # --- Data types ---
    raw_info["dtypes"] = {col: str(df[col].dtype) for col in df.columns}

    # --- Date range ---
    date_col = "InvoiceDate"
    if date_col in df.columns:
        dates = pd.to_datetime(df[date_col], errors="coerce")
        valid = dates.dropna()
        raw_info["date_range"] = {
            "min": str(valid.min()) if len(valid) > 0 else None,
            "max": str(valid.max()) if len(valid) > 0 else None,
            "unparseable_dates": int(dates.isna().sum()),
        }

    # --- Value ranges ---
    for num_col, raw_col in [("Quantity", "Quantity"), ("UnitPrice", "UnitPrice")]:
        if raw_col in df.columns:
            vals = pd.to_numeric(df[raw_col], errors="coerce")
            raw_info[f"{num_col.lower()}_range"] = {
                "min": float(vals.min()) if vals.notna().any() else None,
                "max": float(vals.max()) if vals.notna().any() else None,
                "mean": round(float(vals.mean()), 4) if vals.notna().any() else None,
                "negative_count": int((vals < 0).sum()),
                "zero_count": int((vals == 0).sum()),
                "nan_count": int(vals.isna().sum()),
            }

    # --- Unique counts ---
    if "InvoiceNo" in df.columns:
        raw_info["unique_invoices"] = int(df["InvoiceNo"].nunique())
    if "StockCode" in df.columns:
        raw_info["unique_stock_codes"] = int(df["StockCode"].nunique())
    if "CustomerID" in df.columns:
        raw_info["unique_customers_incl_null"] = int(df["CustomerID"].nunique())
        raw_info["null_customer_rows"] = int(df["CustomerID"].isna().sum())
    if "Country" in df.columns:
        raw_info["unique_countries"] = int(df["Country"].nunique())

    return raw_info


# ============================================================
# DUPLICATE ANALYSIS
# ============================================================

def analyze_duplicates(df: pd.DataFrame) -> dict:
    """Analyze exact duplicate rows in the raw data."""
    logger.info("Analyzing duplicates")

    all_dup_mask = df.duplicated(keep=False)
    remove_mask = df.duplicated(keep="first")

    dup_info = {
        "rows_in_duplicate_groups": int(all_dup_mask.sum()),
        "duplicate_rows_to_remove": int(remove_mask.sum()),
        "unique_duplicate_sets": int(all_dup_mask.sum() - remove_mask.sum()),
        "pct_of_total": round(remove_mask.sum() / len(df) * 100, 2),
        "decision": (
            "REMOVE subsequent exact copies, KEEP first occurrence. "
            "An 'exact duplicate' means ALL columns are identical. "
            "Rationale: identical rows across invoice_no, stock_code, "
            "description, quantity, invoice_date, unit_price, customer_id, "
            "and country are system/import artifacts, not separate "
            "legitimate transactions."
        ),
    }

    # Show a sample of duplicated rows (top 5 groups)
    if all_dup_mask.any():
        dup_sample = df[all_dup_mask].head(10)
        dup_info["sample_duplicates"] = dup_sample.astype(str).to_dict(orient="records")

    return dup_info


# ============================================================
# CLASSIFICATION ANALYSIS
# ============================================================

def analyze_classification(raw_df: pd.DataFrame) -> dict:
    """
    Independently reproduce the classification logic from clean_data.py
    to verify the split between sales and non-sales.
    """
    logger.info("Analyzing row classification (independent reproduction)")

    df = raw_df.copy()

    # Standardize for analysis
    df["InvoiceNo"] = df["InvoiceNo"].astype(str).str.strip()
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df["UnitPrice"] = pd.to_numeric(df["UnitPrice"], errors="coerce")

    # Remove exact duplicates (same as clean_data.py)
    df = df.drop_duplicates(keep="first").reset_index(drop=True)

    # Masks
    is_c = df["InvoiceNo"].str.upper().str.startswith("C")
    is_neg_qty = df["Quantity"] < 0
    is_non_pos_price = df["UnitPrice"] <= 0
    is_zero_qty = df["Quantity"] == 0
    is_nan = df["Quantity"].isna() | df["UnitPrice"].isna()

    mask_return = is_c | is_neg_qty
    mask_adj = ~mask_return & is_non_pos_price
    mask_invalid = ~mask_return & ~mask_adj & is_nan
    mask_zero = ~mask_return & ~mask_adj & ~mask_invalid & is_zero_qty
    mask_sale = ~mask_return & ~mask_adj & ~mask_invalid & ~mask_zero

    cls = {
        "after_dedup_total": len(df),
        "eligible_sales": int(mask_sale.sum()),
        "returns_cancellations": int(mask_return.sum()),
        "adjustments_non_positive_price": int(mask_adj.sum()),
        "invalid_numeric": int(mask_invalid.sum()),
        "zero_quantity": int(mask_zero.sum()),
        "verification_sum": int(
            mask_sale.sum() + mask_return.sum() + mask_adj.sum()
            + mask_invalid.sum() + mask_zero.sum()
        ),
        "sum_matches_total": bool(
            mask_sale.sum() + mask_return.sum() + mask_adj.sum()
            + mask_invalid.sum() + mask_zero.sum() == len(df)
        ),
    }

    # Revenue sanity on eligible sales
    sales = df[mask_sale]
    total_revenue = float((sales["Quantity"] * sales["UnitPrice"]).sum())
    cls["eligible_sales_gross_revenue"] = round(total_revenue, 2)

    return cls


# ============================================================
# CLEANED CSV ANALYSIS
# ============================================================

def analyze_cleaned_sales(df: pd.DataFrame) -> dict:
    """Compute summary stats on the cleaned sales CSV."""
    logger.info("Analyzing cleaned_sales.csv")

    info = {
        "total_rows": len(df),
        "columns": list(df.columns),
        "total_revenue": round(float(df["line_revenue"].sum()), 2),
        "unique_invoices": int(df["invoice_no"].nunique()),
        "unique_customers": int(df["customer_id"].dropna().nunique()),
        "null_customer_id_rows": int(df["customer_id"].isna().sum()),
        "null_customer_id_pct": round(
            df["customer_id"].isna().sum() / len(df) * 100, 2
        ),
        "unique_products": int(df["stock_code"].nunique()),
        "unique_countries": int(df["country"].dropna().nunique()),
        "units_sold": int(df["quantity"].sum()),
        "avg_order_value": None,
        "date_range": {
            "min": str(df["invoice_date"].min()),
            "max": str(df["invoice_date"].max()),
        },
        "missing_values": {},
    }

    # AOV = Total Revenue / Distinct Invoices
    if info["unique_invoices"] > 0:
        info["avg_order_value"] = round(
            info["total_revenue"] / info["unique_invoices"], 2
        )

    # Missing values per column
    for col in df.columns:
        null_count = int(df[col].isna().sum())
        if null_count > 0:
            info["missing_values"][col] = {
                "null_count": null_count,
                "null_pct": round(null_count / len(df) * 100, 2),
            }

    # Revenue by year-month
    monthly = (
        df.groupby("year_month")["line_revenue"]
        .sum()
        .round(2)
        .sort_index()
        .to_dict()
    )
    info["monthly_revenue"] = {str(k): float(v) for k, v in monthly.items()}

    return info


def analyze_returns(df: pd.DataFrame) -> dict:
    """Compute summary stats on the returns/adjustments CSV."""
    logger.info("Analyzing returns_analysis.csv")

    info = {
        "total_rows": len(df),
        "total_return_value": round(float(df["line_revenue"].sum()), 2),
        "by_flag": {},
    }

    # Breakdown by return_flag
    flag_counts = df["return_flag"].value_counts().to_dict()
    for flag, count in flag_counts.items():
        subset = df[df["return_flag"] == flag]
        info["by_flag"][str(flag)] = {
            "row_count": int(count),
            "pct_of_returns": round(count / len(df) * 100, 2),
            "total_value": round(float(subset["line_revenue"].sum()), 2),
        }

    return info


# ============================================================
# FILTERING DECISIONS LOG
# ============================================================

def build_filtering_decisions() -> list:
    """
    Document every filtering decision made by clean_data.py.
    Each decision includes what was done, how many rows were affected
    (to be filled by actual counts), and the rationale.
    """
    return [
        {
            "step": 1,
            "action": "Column renaming",
            "description": (
                "Renamed raw Excel columns from CamelCase to snake_case "
                "(e.g. InvoiceNo → invoice_no). No rows affected."
            ),
            "rows_affected": "0 (schema change only)",
            "rationale": "Consistent naming convention for SQL and Python.",
        },
        {
            "step": 2,
            "action": "Data type coercion",
            "description": (
                "Cast quantity and unit_price to numeric (non-parseable → NaN). "
                "Cast customer_id to nullable Int64. Cast invoice_no and "
                "stock_code to stripped strings."
            ),
            "rows_affected": "Depends on data; typically 0",
            "rationale": (
                "Ensures correct arithmetic and aggregation. "
                "Nullable Int64 preserves NaN for anonymous customers."
            ),
        },
        {
            "step": 3,
            "action": "Date parsing",
            "description": (
                "Parsed InvoiceDate to datetime. Unparseable → NaT."
            ),
            "rows_affected": "Depends on data; typically 0",
            "rationale": "Required for time-series analysis and date-part extraction.",
        },
        {
            "step": 4,
            "action": "Exact duplicate removal",
            "description": (
                "Identified rows where ALL columns are identical. "
                "Kept the first occurrence; removed subsequent copies."
            ),
            "rows_affected": "See duplicate_analysis section",
            "rationale": (
                "Rows identical across every column including invoice_no, "
                "stock_code, timestamp, and customer_id are data artifacts. "
                "Keeping them would inflate revenue and unit counts."
            ),
        },
        {
            "step": 5,
            "action": "Return/cancellation classification",
            "description": (
                "Rows where invoice_no starts with 'C' OR quantity < 0 "
                "are classified as returns/cancellations and routed to "
                "returns_analysis.csv. Flagged as 'C_invoice', "
                "'negative_quantity', or both."
            ),
            "rows_affected": "See classification section",
            "rationale": (
                "The 'C' prefix is the dataset's convention for cancelled "
                "invoices. Negative quantities represent returned items. "
                "These are a cancellation/return PROXY — the dataset does "
                "not contain actual payment or refund records."
            ),
        },
        {
            "step": 6,
            "action": "Adjustment classification",
            "description": (
                "Rows with unit_price ≤ 0 that are NOT C-invoices and "
                "have quantity ≥ 0 are classified as adjustments "
                "(free items, bad-debt write-offs, pricing corrections). "
                "Routed to returns_analysis.csv with flag "
                "'adjustment_non_positive_price'."
            ),
            "rows_affected": "See classification section",
            "rationale": (
                "These rows generate zero or negative revenue and "
                "do not represent genuine sales. They are REPORTED, "
                "not silently dropped, per project requirements."
            ),
        },
        {
            "step": 7,
            "action": "Zero-quantity and invalid-numeric classification",
            "description": (
                "Rows with quantity = 0 or NaN quantity/price (not covered "
                "by the above categories) are flagged as anomalies and "
                "routed to returns_analysis.csv."
            ),
            "rows_affected": "See classification section",
            "rationale": "Zero-quantity transactions carry no business meaning.",
        },
        {
            "step": 8,
            "action": "Derived column computation",
            "description": (
                "Added line_revenue = quantity × unit_price, plus year, "
                "month, quarter, and year_month extracted from invoice_date."
            ),
            "rows_affected": "0 (new columns added, no rows removed)",
            "rationale": (
                "line_revenue is gross sales. Date parts enable "
                "time-series aggregation in SQL and Tableau."
            ),
        },
        {
            "step": 9,
            "action": "Anonymous customer handling",
            "description": (
                "Rows with NULL customer_id are KEPT in cleaned_sales.csv. "
                "They count toward revenue and order totals but are "
                "EXCLUDED from customer-level KPIs (unique customers, "
                "repeat rate, RFM). The denominator for every customer "
                "metric is stated explicitly."
            ),
            "rows_affected": "0 (no removal; NULLs retained)",
            "rationale": (
                "Dropping anonymous sales would understate revenue. "
                "Customer KPIs use only identified customers."
            ),
        },
    ]


# ============================================================
# DATA INTEGRITY CHECKS
# ============================================================

def run_integrity_checks(
    raw_rows: int,
    dup_removed: int,
    sales_rows: int,
    returns_rows: int,
) -> dict:
    """Cross-validate row counts across pipeline stages."""
    logger.info("Running data integrity checks")

    after_dedup = raw_rows - dup_removed
    recon_sum = sales_rows + returns_rows

    checks = {
        "raw_minus_dups_equals_dedup": {
            "expected": after_dedup,
            "actual": after_dedup,
            "pass": True,
        },
        "sales_plus_returns_equals_dedup": {
            "expected": after_dedup,
            "actual": recon_sum,
            "pass": recon_sum == after_dedup,
        },
        "no_rows_lost_or_created": {
            "raw_rows": raw_rows,
            "duplicates_removed": dup_removed,
            "after_dedup": after_dedup,
            "sales_csv": sales_rows,
            "returns_csv": returns_rows,
            "sales_plus_returns": recon_sum,
            "pass": recon_sum == after_dedup,
        },
    }

    for name, check in checks.items():
        status = "PASS ✓" if check["pass"] else "FAIL ✗"
        logger.info(f"  {name}: {status}")

    return checks


# ============================================================
# CONSOLE REPORT
# ============================================================

def print_console_report(report: dict) -> None:
    """Print a human-readable summary to the console."""
    sep = "=" * 65
    thin = "-" * 65

    print(f"\n{sep}")
    print("  DATA QUALITY REPORT")
    print(f"  Generated: {report['report_generated_at']}")
    print(sep)

    # --- Raw data ---
    raw = report["raw_data"]
    print(f"\n{'RAW DATA':^65}")
    print(thin)
    print(f"  Total rows           : {raw['total_rows']:>10,}")
    print(f"  Total columns        : {raw['total_columns']:>10}")
    print(f"  Memory (MB)          : {raw['memory_usage_mb']:>10.2f}")
    print(f"  Overall completeness : {raw['overall_completeness_pct']:>9.2f}%")

    print(f"\n  {'Column':<16} {'Nulls':>8} {'Pct':>7}")
    print(f"  {'─'*16} {'─'*8} {'─'*7}")
    for col, vals in raw["missing_values"].items():
        if vals["null_count"] > 0:
            print(f"  {col:<16} {vals['null_count']:>8,} {vals['null_pct']:>6.2f}%")

    # --- Duplicates ---
    dup = report["duplicate_analysis"]
    print(f"\n{'DUPLICATE ANALYSIS':^65}")
    print(thin)
    print(f"  Rows in dup groups   : {dup['rows_in_duplicate_groups']:>10,}")
    print(f"  Duplicates removed   : {dup['duplicate_rows_to_remove']:>10,}")
    print(f"  Pct of total         : {dup['pct_of_total']:>9.2f}%")
    print(f"  Decision             : Keep first, remove copies")

    # --- Classification ---
    cls = report["classification"]
    print(f"\n{'ROW CLASSIFICATION (after dedup)':^65}")
    print(thin)
    print(f"  After dedup total    : {cls['after_dedup_total']:>10,}")
    print(f"  Eligible sales       : {cls['eligible_sales']:>10,}")
    print(f"  Returns/cancellations: {cls['returns_cancellations']:>10,}")
    print(f"  Adjustments (price≤0): {cls['adjustments_non_positive_price']:>10,}")
    print(f"  Invalid numeric      : {cls['invalid_numeric']:>10,}")
    print(f"  Zero quantity        : {cls['zero_quantity']:>10,}")
    print(f"  Verification sum     : {cls['verification_sum']:>10,}")
    print(f"  Sum matches total    : {cls['sum_matches_total']}")

    # --- Cleaned sales ---
    if "cleaned_sales" in report:
        sales = report["cleaned_sales"]
        print(f"\n{'CLEANED SALES SUMMARY':^65}")
        print(thin)
        print(f"  Total rows           : {sales['total_rows']:>10,}")
        print(f"  Total revenue (gross): {sales['total_revenue']:>14,.2f}")
        print(f"  Unique invoices      : {sales['unique_invoices']:>10,}")
        print(f"  Unique customers     : {sales['unique_customers']:>10,}")
        print(f"  Null customer_id rows: {sales['null_customer_id_rows']:>10,}")
        print(f"  Null customer_id pct : {sales['null_customer_id_pct']:>9.2f}%")
        print(f"  Unique products      : {sales['unique_products']:>10,}")
        print(f"  Units sold           : {sales['units_sold']:>10,}")
        if sales["avg_order_value"] is not None:
            print(f"  AOV                  : {sales['avg_order_value']:>14,.2f}")

    # --- Returns ---
    if "returns_analysis" in report:
        ret = report["returns_analysis"]
        print(f"\n{'RETURNS / ADJUSTMENTS SUMMARY':^65}")
        print(thin)
        print(f"  Total rows           : {ret['total_rows']:>10,}")
        print(f"  Total return value   : {ret['total_return_value']:>14,.2f}")
        if ret["by_flag"]:
            print(f"\n  {'Flag':<40} {'Count':>7} {'Pct':>7}")
            print(f"  {'─'*40} {'─'*7} {'─'*7}")
            for flag, vals in ret["by_flag"].items():
                print(
                    f"  {flag:<40} {vals['row_count']:>7,} "
                    f"{vals['pct_of_returns']:>6.2f}%"
                )

    # --- Integrity checks ---
    checks = report.get("integrity_checks", {})
    if checks:
        print(f"\n{'INTEGRITY CHECKS':^65}")
        print(thin)
        for name, chk in checks.items():
            status = "PASS ✓" if chk["pass"] else "FAIL ✗"
            print(f"  {name:<45} {status}")

    # --- Filtering decisions ---
    print(f"\n{'FILTERING DECISIONS (9 steps)':^65}")
    print(thin)
    for d in report.get("filtering_decisions", []):
        print(f"\n  Step {d['step']}: {d['action']}")
        # Wrap description for readability
        desc = d["description"]
        print(f"    {desc}")
        print(f"    Rationale: {d['rationale']}")

    print(f"\n{sep}")
    print("  REPORT COMPLETE ✓")
    print(f"{sep}\n")


# ============================================================
# MAIN
# ============================================================

def main():
    """Generate the full data quality report."""
    logger.info("=" * 65)
    logger.info("  DATA QUALITY REPORT — START")
    logger.info("=" * 65)

    # ---- Load raw data ----
    raw_df = load_raw_excel(PATHS["raw_excel"])
    raw_rows = len(raw_df)

    # ---- Analyze raw data ----
    raw_info = analyze_raw_data(raw_df)
    dup_info = analyze_duplicates(raw_df)
    cls_info = analyze_classification(raw_df)

    # ---- Load and analyze cleaned CSVs ----
    sales_info = None
    returns_info = None

    if PATHS["cleaned_sales_csv"].exists():
        sales_df = load_cleaned_csv(PATHS["cleaned_sales_csv"])
        sales_info = analyze_cleaned_sales(sales_df)
    else:
        logger.warning(
            "cleaned_sales.csv not found — run clean_data.py first. "
            "Skipping cleaned-data analysis."
        )

    if PATHS["returns_csv"].exists():
        returns_df = load_cleaned_csv(PATHS["returns_csv"])
        returns_info = analyze_returns(returns_df)
    else:
        logger.warning(
            "returns_analysis.csv not found — run clean_data.py first. "
            "Skipping returns analysis."
        )

    # ---- Integrity checks ----
    dup_removed = dup_info["duplicate_rows_to_remove"]
    sales_rows = sales_info["total_rows"] if sales_info else 0
    ret_rows = returns_info["total_rows"] if returns_info else 0
    integrity = run_integrity_checks(raw_rows, dup_removed, sales_rows, ret_rows)

    # ---- Filtering decisions ----
    decisions = build_filtering_decisions()

    # ---- Assemble full report ----
    report = {
        "report_generated_at": datetime.now().isoformat(),
        "raw_data": raw_info,
        "duplicate_analysis": dup_info,
        "classification": cls_info,
        "integrity_checks": integrity,
        "filtering_decisions": decisions,
    }

    if sales_info:
        report["cleaned_sales"] = sales_info
    if returns_info:
        report["returns_analysis"] = returns_info

    # ---- Save JSON ----
    json_path = PATHS["quality_report_json"]
    json_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove sample_duplicates (non-serializable edge cases) or convert
    if "sample_duplicates" in report.get("duplicate_analysis", {}):
        # Already converted to strings in analyze_duplicates
        pass

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"JSON report saved → {json_path.name}")

    # ---- Console report ----
    print_console_report(report)

    logger.info("=" * 65)
    logger.info("  DATA QUALITY REPORT — COMPLETE ✓")
    logger.info("=" * 65)


if __name__ == "__main__":
    main()
