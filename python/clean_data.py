"""
clean_data.py — Data Cleaning & Transformation Pipeline
=========================================================
Loads the raw UCI Online Retail Excel file, validates, cleans, classifies
rows, and exports two CSVs: cleaned_sales.csv and returns_analysis.csv.

Pipeline steps:
    1. Load raw Excel file (Online Retail.xlsx)
    2. Standardize column names to snake_case and fix data types
    3. Parse and validate dates
    4. Detect and remove exact duplicate rows (documented decision)
    5. Classify rows: eligible sales vs returns/cancellations vs adjustments
    6. Compute derived columns (line_revenue, year, month, quarter, year_month)
    7. Export cleaned CSVs

Usage:
    cd ecommerce-sales-analytics
    python python/clean_data.py
"""

import sys
import numpy as np
import pandas as pd

from config import PATHS, CLEANED_COLUMNS, RETURNS_COLUMNS, setup_logging

logger = setup_logging("clean_data")

# ============================================================
# COLUMN MAPPING: Raw Excel → Standardized snake_case
# ============================================================

COLUMN_MAPPING = {
    "InvoiceNo": "invoice_no",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "UnitPrice": "unit_price",
    "CustomerID": "customer_id",
    "Country": "country",
}


# ============================================================
# STEP 1: LOAD RAW DATA
# ============================================================

def load_raw_data(filepath) -> pd.DataFrame:
    """
    Load the raw Excel file and return an unmodified DataFrame.

    Exits with an error message if the file is missing.
    """
    logger.info(f"Loading raw data from: {filepath}")

    if not filepath.exists():
        logger.error(f"FILE NOT FOUND: {filepath}")
        logger.error(
            "Download the dataset from: "
            "https://archive.ics.uci.edu/dataset/352/online+retail\n"
            "Place 'Online Retail.xlsx' in the data/ folder."
        )
        sys.exit(1)

    df = pd.read_excel(filepath, engine="openpyxl")
    logger.info(f"Loaded {len(df):,} rows × {len(df.columns)} columns")
    logger.info(f"Raw columns: {list(df.columns)}")
    return df


# ============================================================
# STEP 2: STANDARDIZE COLUMNS AND TYPES
# ============================================================

def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename columns to snake_case and coerce to appropriate data types.

    - invoice_no, stock_code: stripped strings
    - description, country: stripped strings (NaN preserved)
    - quantity, unit_price: numeric (non-numeric → NaN)
    - customer_id: nullable Int64 (NaN = anonymous customer)
    """
    logger.info("Standardizing column names and data types")

    df = df.rename(columns=COLUMN_MAPPING)

    # --- String columns ---
    df["invoice_no"] = df["invoice_no"].astype(str).str.strip()
    df["stock_code"] = df["stock_code"].astype(str).str.strip()

    # Description: convert to string, then restore genuine NaN
    df["description"] = df["description"].astype(str).str.strip()
    df.loc[df["description"].isin(["nan", "None", ""]), "description"] = np.nan

    # Country: same treatment
    df["country"] = df["country"].astype(str).str.strip()
    df.loc[df["country"].isin(["nan", "None", ""]), "country"] = np.nan

    # --- Numeric columns ---
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")

    # Customer ID: nullable integer (NaN = anonymous customer)
    df["customer_id"] = pd.to_numeric(df["customer_id"], errors="coerce")
    df["customer_id"] = df["customer_id"].astype("Int64")

    # --- Report type coercion issues ---
    nan_qty = df["quantity"].isna().sum()
    nan_price = df["unit_price"].isna().sum()
    if nan_qty > 0:
        logger.warning(f"Non-numeric quantity values coerced to NaN: {nan_qty:,}")
    if nan_price > 0:
        logger.warning(f"Non-numeric unit_price values coerced to NaN: {nan_price:,}")

    logger.info("Column standardization complete")
    return df


# ============================================================
# STEP 3: PARSE AND VALIDATE DATES
# ============================================================

def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse invoice_date to datetime. Unparseable values become NaT.
    """
    logger.info("Parsing invoice dates")

    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")

    null_dates = df["invoice_date"].isna().sum()
    if null_dates > 0:
        logger.warning(f"Unparseable dates (NaT): {null_dates:,}")
    else:
        logger.info("All dates parsed successfully")

    valid_dates = df["invoice_date"].dropna()
    if len(valid_dates) > 0:
        logger.info(
            f"Date range: {valid_dates.min().strftime('%Y-%m-%d')} → "
            f"{valid_dates.max().strftime('%Y-%m-%d')}"
        )

    return df


# ============================================================
# STEP 4: DETECT AND REMOVE EXACT DUPLICATES
# ============================================================

def detect_and_remove_duplicates(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """
    Find exact duplicate rows, report them, and remove copies.

    Decision
    --------
    Keep the FIRST occurrence of each duplicate set; remove all subsequent
    exact copies.

    Rationale
    ---------
    Rows identical across ALL 8 columns (InvoiceNo, StockCode, Description,
    Quantity, InvoiceDate, UnitPrice, CustomerID, Country) are most likely
    data-entry or system-import artifacts, not separate legitimate
    transactions. A single invoice line for the same product, quantity, and
    price at the same timestamp is not expected to appear twice.

    Returns
    -------
    (deduplicated_df, duplicate_stats_dict)
    """
    logger.info("Detecting exact duplicate rows")

    # Mark ALL rows that belong to a duplicate group
    all_dup_mask = df.duplicated(keep=False)
    total_in_dup_groups = int(all_dup_mask.sum())

    # Mark rows to REMOVE (keep='first')
    remove_mask = df.duplicated(keep="first")
    duplicates_to_remove = int(remove_mask.sum())

    dup_stats = {
        "rows_in_duplicate_groups": total_in_dup_groups,
        "duplicate_rows_removed": duplicates_to_remove,
        "duplicate_rows_kept": total_in_dup_groups - duplicates_to_remove,
        "removal_decision": (
            "Kept the first occurrence of each duplicate set and removed "
            "all subsequent exact copies. Rows are considered exact "
            "duplicates only when ALL columns match (invoice_no, stock_code, "
            "description, quantity, invoice_date, unit_price, customer_id, "
            "country). Such rows are most likely data-entry or system-import "
            "artifacts, not separate legitimate transactions."
        ),
    }

    if duplicates_to_remove > 0:
        logger.info(
            f"Duplicate groups contain {total_in_dup_groups:,} rows total; "
            f"removing {duplicates_to_remove:,} copies, keeping "
            f"{total_in_dup_groups - duplicates_to_remove:,} originals"
        )
        df = df[~remove_mask].reset_index(drop=True)
        logger.info(f"Rows after deduplication: {len(df):,}")
    else:
        logger.info("No exact duplicate rows found")

    return df, dup_stats


# ============================================================
# STEP 5: CLASSIFY ROWS
# ============================================================

def classify_rows(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Classify each row into mutually exclusive categories.

    Categories (evaluated in priority order)
    -----------------------------------------
    1. RETURN / CANCELLATION
       Condition: invoice_no starts with 'C'  OR  quantity < 0
       Flags:     'C_invoice', 'negative_quantity', or 'C_invoice|negative_quantity'
       Note:      This is a cancellation/return **proxy**, not a verified refund.

    2. ADJUSTMENT (non-positive price, not a cancellation)
       Condition: unit_price <= 0  AND  NOT C-invoice  AND  quantity >= 0
       Flag:      'adjustment_non_positive_price'
       Includes:  Free-of-charge items, bad-debt write-offs, pricing corrections.
       These are reported, NOT silently dropped.

    3. INVALID NUMERIC (NaN quantity or price after coercion)
       Condition: quantity is NaN  OR  unit_price is NaN  (not caught above)
       Flag:      'invalid_numeric'

    4. ZERO QUANTITY (edge case)
       Condition: quantity == 0 AND not covered above
       Flag:      'zero_quantity'

    5. ELIGIBLE SALE (everything remaining)
       Condition: NOT C-invoice  AND  quantity > 0  AND  unit_price > 0
       Goes to cleaned_sales.csv.

    Returns
    -------
    (sales_df, non_sales_df, classification_stats_dict)
    """
    logger.info("Classifying rows into sales vs non-sale transactions")

    # ---- Boolean masks ----
    is_c_invoice = df["invoice_no"].str.upper().str.startswith("C")
    is_negative_qty = df["quantity"] < 0
    is_non_positive_price = df["unit_price"] <= 0
    is_zero_qty = df["quantity"] == 0
    is_nan_qty = df["quantity"].isna()
    is_nan_price = df["unit_price"].isna()

    # ---- Priority 1: Return / cancellation ----
    mask_return = is_c_invoice | is_negative_qty

    # ---- Priority 2: Adjustment (non-positive price, NOT already a return) ----
    mask_adjustment = ~mask_return & is_non_positive_price

    # ---- Priority 3: Invalid numeric (NaN qty/price, not caught above) ----
    mask_invalid = ~mask_return & ~mask_adjustment & (is_nan_qty | is_nan_price)

    # ---- Priority 4: Zero quantity (edge case) ----
    mask_zero_qty = ~mask_return & ~mask_adjustment & ~mask_invalid & is_zero_qty

    # ---- Priority 5: Eligible sale ----
    mask_sale = ~mask_return & ~mask_adjustment & ~mask_invalid & ~mask_zero_qty

    # ---- Build return_flag column (vectorized with numpy) ----
    flags = np.full(len(df), "", dtype=object)

    # C_invoice + negative_quantity (both)
    both_mask = is_c_invoice & is_negative_qty
    flags[both_mask.values] = "C_invoice|negative_quantity"

    # C_invoice only (positive or zero qty)
    c_only = is_c_invoice & ~is_negative_qty
    flags[c_only.values] = "C_invoice"

    # negative_quantity only (no C prefix)
    neg_only = ~is_c_invoice & is_negative_qty
    flags[neg_only.values] = "negative_quantity"

    # Adjustments
    flags[mask_adjustment.values] = "adjustment_non_positive_price"

    # Invalid numeric
    flags[mask_invalid.values] = "invalid_numeric"

    # Zero quantity
    flags[mask_zero_qty.values] = "zero_quantity"

    df = df.copy()
    df["return_flag"] = flags

    # ---- Split ----
    sales_df = df[mask_sale].copy().reset_index(drop=True)
    non_sale_mask = mask_return | mask_adjustment | mask_invalid | mask_zero_qty
    non_sales_df = df[non_sale_mask].copy().reset_index(drop=True)

    # ---- Statistics ----
    cls_stats = {
        "eligible_sales": int(mask_sale.sum()),
        "returns_cancellations": {
            "total": int(mask_return.sum()),
            "C_invoice_only": int(c_only.sum()),
            "negative_quantity_only": int(neg_only.sum()),
            "both_C_and_negative": int(both_mask.sum()),
        },
        "adjustments_non_positive_price": int(mask_adjustment.sum()),
        "invalid_numeric": int(mask_invalid.sum()),
        "zero_quantity_anomalies": int(mask_zero_qty.sum()),
        "total_non_sale_rows": int(non_sale_mask.sum()),
        "classification_rules": {
            "eligible_sale": (
                "invoice_no does NOT start with 'C' AND "
                "quantity > 0 AND unit_price > 0."
            ),
            "return_cancellation": (
                "invoice_no starts with 'C' OR quantity < 0. "
                "This is a cancellation/return PROXY — not a verified "
                "refund. The dataset does not contain payment or refund data."
            ),
            "adjustment": (
                "unit_price <= 0 AND NOT a C-invoice AND quantity >= 0. "
                "Covers free-of-charge items, bad-debt write-offs, "
                "and pricing adjustments. Reported separately, never "
                "silently dropped."
            ),
            "invalid_numeric": (
                "Quantity or unit_price could not be parsed as a number. "
                "These rows are segregated for investigation."
            ),
            "zero_quantity": (
                "quantity == 0, positive price, non-C invoice. "
                "Rare anomaly — likely a data-entry error."
            ),
        },
    }

    logger.info(f"  Eligible sales       : {mask_sale.sum():>8,}")
    logger.info(f"  Returns/cancellations: {mask_return.sum():>8,}")
    logger.info(f"    ├─ C_invoice only  : {c_only.sum():>8,}")
    logger.info(f"    ├─ negative_qty    : {neg_only.sum():>8,}")
    logger.info(f"    └─ both            : {both_mask.sum():>8,}")
    logger.info(f"  Adjustments (price≤0): {mask_adjustment.sum():>8,}")
    logger.info(f"  Invalid numeric      : {mask_invalid.sum():>8,}")
    logger.info(f"  Zero quantity         : {mask_zero_qty.sum():>8,}")

    return sales_df, non_sales_df, cls_stats


# ============================================================
# STEP 6: ADD DERIVED COLUMNS
# ============================================================

def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute derived columns from the cleaned data.

    - line_revenue = quantity × unit_price  (gross; negative for returns)
    - year, month, quarter  from invoice_date
    - year_month  in 'YYYY-MM' format
    """
    logger.info("Computing derived columns")

    # Revenue
    df["line_revenue"] = (df["quantity"] * df["unit_price"]).round(2)

    # Date parts (nullable Int64 to handle any NaT gracefully)
    df["year"] = df["invoice_date"].dt.year.astype("Int64")
    df["month"] = df["invoice_date"].dt.month.astype("Int64")
    df["quarter"] = df["invoice_date"].dt.quarter.astype("Int64")
    df["year_month"] = df["invoice_date"].dt.to_period("M").astype(str)
    # to_period("M").astype(str) produces 'YYYY-MM'; NaT → 'NaT'
    df.loc[df["year_month"] == "NaT", "year_month"] = np.nan

    total_rev = df["line_revenue"].sum()
    logger.info(
        f"  line_revenue range: "
        f"{df['line_revenue'].min():,.2f} → {df['line_revenue'].max():,.2f}"
    )
    logger.info(f"  Total line_revenue : {total_rev:,.2f}")

    return df


# ============================================================
# STEP 7: EXPORT
# ============================================================

def export_data(
    sales_df: pd.DataFrame,
    returns_df: pd.DataFrame,
) -> tuple:
    """
    Write cleaned DataFrames to CSV files.

    - cleaned_sales.csv   : columns from CLEANED_COLUMNS (no return_flag)
    - returns_analysis.csv: columns from RETURNS_COLUMNS (includes return_flag)
    """
    sales_path = PATHS["cleaned_sales_csv"]
    returns_path = PATHS["returns_csv"]

    # Ensure output directory exists
    sales_path.parent.mkdir(parents=True, exist_ok=True)

    # Sales
    sales_export = sales_df[CLEANED_COLUMNS]
    sales_export.to_csv(sales_path, index=False, encoding="utf-8-sig")
    logger.info(f"Exported {len(sales_export):,} sales rows → {sales_path.name}")

    # Returns / adjustments
    returns_export = returns_df[RETURNS_COLUMNS]
    returns_export.to_csv(returns_path, index=False, encoding="utf-8-sig")
    logger.info(
        f"Exported {len(returns_export):,} return/adjustment rows → "
        f"{returns_path.name}"
    )

    return sales_path, returns_path


# ============================================================
# MAIN PIPELINE ORCHESTRATOR
# ============================================================

def main():
    """Execute the full data-cleaning pipeline end to end."""
    logger.info("=" * 65)
    logger.info("  DATA CLEANING PIPELINE — START")
    logger.info("=" * 65)

    # Step 1 — Load
    raw_df = load_raw_data(PATHS["raw_excel"])
    raw_row_count = len(raw_df)

    # Step 2 — Standardize
    df = standardize_columns(raw_df)

    # Step 3 — Parse dates
    df = parse_dates(df)

    # Step 4 — Deduplicate
    df, dup_stats = detect_and_remove_duplicates(df)
    after_dedup = len(df)

    # Step 5 — Classify
    sales_df, returns_df, cls_stats = classify_rows(df)

    # Step 6 — Derived columns (both sets)
    sales_df = add_derived_columns(sales_df)
    returns_df = add_derived_columns(returns_df)

    # Step 7 — Export
    export_data(sales_df, returns_df)

    # ---- Summary ----
    logger.info("=" * 65)
    logger.info("  PIPELINE SUMMARY")
    logger.info("=" * 65)
    logger.info(f"  Raw rows loaded           : {raw_row_count:>10,}")
    logger.info(f"  Exact duplicates removed   : {dup_stats['duplicate_rows_removed']:>10,}")
    logger.info(f"  Rows after dedup           : {after_dedup:>10,}")
    logger.info(f"  → Eligible sales (CSV)     : {len(sales_df):>10,}")
    logger.info(f"  → Returns/adjustments (CSV): {len(returns_df):>10,}")
    verification = len(sales_df) + len(returns_df)
    match = verification == after_dedup
    logger.info(f"  Verification sum           : {verification:>10,}")
    logger.info(f"  Matches dedup count        : {match}")
    if not match:
        logger.error(
            f"  ⚠ MISMATCH: sales({len(sales_df)}) + "
            f"returns({len(returns_df)}) = {verification} "
            f"≠ dedup({after_dedup})"
        )

    logger.info("=" * 65)
    logger.info("  DATA CLEANING PIPELINE — COMPLETE ✓")
    logger.info("=" * 65)


if __name__ == "__main__":
    main()
