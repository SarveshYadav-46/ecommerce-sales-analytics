"""
validate_metrics.py — Pandas vs SQL Cross-Validation Engine
============================================================
Independently recomputes core e-commerce KPIs directly in Pandas from
cleaned_sales.csv, queries the exact same metrics from the SQL database
(fact_sales), compares them side-by-side with strict numerical tolerances,
and prints a standardized PASS/FAIL audit report.

Core KPIs validated:
    1. Total Gross Revenue (line_revenue sum)
    2. Total Orders (distinct invoice_no)
    3. Identified Unique Customers (distinct non-null customer_id)
    4. Total Units Sold (quantity sum)
    5. Average Order Value (AOV = Revenue / Orders)
    6. Customer Repeat Rate (% customers with >= 2 distinct orders)

Usage:
    cd ecommerce-sales-analytics
    python python/validate_metrics.py
    python python/validate_metrics.py --strict
    python python/validate_metrics.py --csv-only
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Tuple

import pandas as pd
from sqlalchemy import create_engine, text

from config import PATHS, get_db_url, setup_logging

logger = setup_logging("validate_metrics")


# ============================================================
# 1. PANDAS METRIC RECOMPUTATION
# ============================================================

def compute_pandas_metrics(sales_path: Path = None) -> Dict[str, Any]:
    """
    Independently recompute core KPIs from cleaned_sales.csv using Pandas.

    Conventions:
      • Revenue = sum of line_revenue across all valid sales.
      • Orders = distinct invoice_no count.
      • Customers = distinct non-null customer_id count.
      • Units = sum of quantity.
      • AOV = total_revenue / total_orders.
      • Repeat Rate = identified customers with >= 2 orders / total identified customers.

    Parameters
    ----------
    sales_path : Path, optional
        Path to cleaned_sales.csv. Defaults to PATHS["cleaned_sales_csv"].

    Returns
    -------
    dict
        Dictionary of computed metric names and numerical values.
    """
    path = sales_path or PATHS["cleaned_sales_csv"]
    if not path.exists():
        logger.error(f"Cleaned sales CSV not found: {path}")
        logger.error("Run python/clean_data.py first.")
        sys.exit(1)

    logger.info(f"Computing baseline metrics in Pandas from: {path}")
    df = pd.read_csv(
        path,
        dtype={
            "invoice_no": str,
            "stock_code": str,
            "customer_id": "Int64",
            "quantity": int,
            "unit_price": float,
            "line_revenue": float,
        },
    )

    total_revenue = float(df["line_revenue"].sum())
    total_orders = int(df["invoice_no"].nunique())
    total_units = int(df["quantity"].sum())

    # Customer metrics (identified customers only)
    identified_cust = df.dropna(subset=["customer_id"])
    unique_customers = int(identified_cust["customer_id"].nunique())

    # Average Order Value
    aov = total_revenue / total_orders if total_orders > 0 else 0.0

    # Repeat Purchase Rate
    cust_order_counts = identified_cust.groupby("customer_id")["invoice_no"].nunique()
    repeat_customers = int((cust_order_counts >= 2).sum())
    repeat_rate_pct = (
        (repeat_customers / unique_customers * 100.0)
        if unique_customers > 0
        else 0.0
    )

    metrics = {
        "total_revenue": round(total_revenue, 2),
        "total_orders": total_orders,
        "unique_customers": unique_customers,
        "total_units": total_units,
        "aov": round(aov, 2),
        "repeat_rate_pct": round(repeat_rate_pct, 2),
        "repeat_customers": repeat_customers,
        "total_sales_rows": len(df),
    }

    logger.info("Pandas KPI recomputation complete:")
    logger.info(f"  • Total Revenue     : ${metrics['total_revenue']:,.2f}")
    logger.info(f"  • Total Orders      : {metrics['total_orders']:,}")
    logger.info(f"  • Unique Customers  : {metrics['unique_customers']:,}")
    logger.info(f"  • Total Units Sold  : {metrics['total_units']:,}")
    logger.info(f"  • AOV               : ${metrics['aov']:,.2f}")
    logger.info(f"  • Repeat Rate       : {metrics['repeat_rate_pct']:.2f}%")
    return metrics


# ============================================================
# 2. SQL METRIC QUERYING
# ============================================================

def query_sql_metrics() -> Dict[str, Any]:
    """
    Query the identical KPIs from the database (fact_sales).

    Returns
    -------
    dict
        Dictionary of SQL-computed metrics, or None if the database is unreachable.
    """
    logger.info("Connecting to SQL database to query validation metrics...")

    try:
        url = get_db_url()
        engine = create_engine(url)

        with engine.connect() as conn:
            # Check if fact_sales table exists and has rows
            count_check = conn.execute(text("SELECT COUNT(*) FROM fact_sales;")).scalar()
            if count_check == 0:
                logger.warning("Table 'fact_sales' exists but contains 0 rows.")
                logger.warning("Run 'python python/load_database.py' first.")
                return None

            logger.info(f"Connected to database. fact_sales has {count_check:,} rows.")

            # Query 1: Top-level sales aggregation
            q1 = text("""
                SELECT
                    ROUND(SUM(line_revenue), 2)    AS total_revenue,
                    COUNT(DISTINCT invoice_no)     AS total_orders,
                    SUM(quantity)                  AS total_units,
                    ROUND(SUM(line_revenue) / COUNT(DISTINCT invoice_no), 2) AS aov
                FROM fact_sales;
            """)
            r1 = conn.execute(q1).fetchone()

            # Query 2: Identified customer count
            q2 = text("""
                SELECT COUNT(DISTINCT customer_id) AS unique_customers
                FROM fact_sales
                WHERE customer_id IS NOT NULL;
            """)
            r2 = conn.execute(q2).fetchone()

            # Query 3: Repeat customer rate
            q3 = text("""
                WITH cust_orders AS (
                    SELECT
                        customer_id,
                        COUNT(DISTINCT invoice_no) AS order_count
                    FROM fact_sales
                    WHERE customer_id IS NOT NULL
                    GROUP BY customer_id
                )
                SELECT
                    COUNT(*) AS total_customers,
                    SUM(CASE WHEN order_count >= 2 THEN 1 ELSE 0 END) AS repeat_customers,
                    ROUND(
                        SUM(CASE WHEN order_count >= 2 THEN 1.0 ELSE 0.0 END)
                        / COUNT(*) * 100, 2
                    ) AS repeat_rate_pct
                FROM cust_orders;
            """)
            r3 = conn.execute(q3).fetchone()

        sql_metrics = {
            "total_revenue": float(r1[0]),
            "total_orders": int(r1[1]),
            "total_units": int(r1[2]),
            "aov": float(r1[3]),
            "unique_customers": int(r2[0]),
            "repeat_customers": int(r3[1]),
            "repeat_rate_pct": float(r3[2]),
        }

        logger.info("SQL metrics retrieved successfully.")
        return sql_metrics

    except Exception as e:
        logger.warning(f"Could not retrieve SQL metrics: {e}")
        return None


# ============================================================
# 3. RECONCILIATION AND TOLERANCE COMPARISON
# ============================================================

# Defined tolerances for automated testing
TOLERANCES = {
    "total_revenue": {
        "type": "relative",
        "tolerance": 0.0001,  # 0.01%
        "display_tol": "0.01%",
        "is_currency": True,
    },
    "total_orders": {
        "type": "exact",
        "tolerance": 0,
        "display_tol": "Exact (0)",
        "is_currency": False,
    },
    "unique_customers": {
        "type": "exact",
        "tolerance": 0,
        "display_tol": "Exact (0)",
        "is_currency": False,
    },
    "total_units": {
        "type": "exact",
        "tolerance": 0,
        "display_tol": "Exact (0)",
        "is_currency": False,
    },
    "aov": {
        "type": "absolute",
        "tolerance": 0.05,  # $0.05
        "display_tol": "$0.05",
        "is_currency": True,
    },
    "repeat_rate_pct": {
        "type": "absolute",
        "tolerance": 0.05,  # 0.05 percentage points
        "display_tol": "0.05%",
        "is_currency": False,
        "is_pct": True,
    },
}

METRIC_LABELS = {
    "total_revenue": "Total Gross Revenue",
    "total_orders": "Total Orders (Invoices)",
    "unique_customers": "Unique Identified Customers",
    "total_units": "Total Units Sold",
    "aov": "Average Order Value (AOV)",
    "repeat_rate_pct": "Customer Repeat Rate",
}


def compare_metrics(
    pandas_m: Dict[str, Any], sql_m: Dict[str, Any]
) -> Tuple[bool, list]:
    """
    Compare each metric pair against predefined tolerances.

    Returns
    -------
    tuple[bool, list]
        (all_passed, comparison_records)
    """
    records = []
    all_passed = True

    for key, tol_cfg in TOLERANCES.items():
        val_p = pandas_m.get(key)
        val_s = sql_m.get(key)

        if val_p is None or val_s is None:
            passed = False
            diff_abs = None
            diff_pct = None
        else:
            diff_abs = abs(val_p - val_s)
            diff_pct = (diff_abs / val_p * 100.0) if val_p != 0 else 0.0

            if tol_cfg["type"] == "exact":
                passed = (diff_abs == 0)
            elif tol_cfg["type"] == "absolute":
                passed = (diff_abs <= tol_cfg["tolerance"])
            elif tol_cfg["type"] == "relative":
                passed = ((diff_abs / val_p) <= tol_cfg["tolerance"])
            else:
                passed = (diff_abs <= tol_cfg["tolerance"])

        if not passed:
            all_passed = False

        records.append({
            "key": key,
            "label": METRIC_LABELS.get(key, key),
            "pandas_value": val_p,
            "sql_value": val_s,
            "diff_abs": diff_abs,
            "diff_pct": diff_pct,
            "tolerance": tol_cfg["display_tol"],
            "status": "PASS" if passed else "FAIL",
            "is_currency": tol_cfg.get("is_currency", False),
            "is_pct": tol_cfg.get("is_pct", False),
        })

    return all_passed, records


# ============================================================
# 4. REPORT FORMATTING & EXPORT
# ============================================================

def format_val(val: Any, is_curr: bool = False, is_pct: bool = False) -> str:
    """Format numerical values cleanly for console display."""
    if val is None:
        return "N/A"
    if is_curr:
        return f"${val:,.2f}"
    if is_pct:
        return f"{val:.2f}%"
    if isinstance(val, int):
        return f"{val:,d}"
    if isinstance(val, float):
        return f"{val:,.2f}"
    return str(val)


def print_comparison_table(records: list, all_passed: bool) -> None:
    """Print the final audit table with formatted columns."""
    logger.info("\n" + "=" * 105)
    logger.info("PIPELINE RECONCILIATION AUDIT: PANDAS (CSV) vs SQL (DATABASE)")
    logger.info("=" * 105)

    header = (
        f"{'Metric':<30} | {'Pandas (CSV)':>15} | {'SQL (DB)':>15} | "
        f"{'Diff (Abs)':>12} | {'Diff (%)':>9} | {'Tolerance':<10} | {'Status':<6}"
    )
    logger.info(header)
    logger.info("-" * len(header))

    for r in records:
        p_str = format_val(r["pandas_value"], r["is_currency"], r["is_pct"])
        s_str = format_val(r["sql_value"], r["is_currency"], r["is_pct"])
        diff_str = (
            f"${r['diff_abs']:,.2f}"
            if r["is_currency"]
            else (f"{r['diff_abs']:.4f}" if isinstance(r["diff_abs"], float) else str(r["diff_abs"]))
        )
        diff_pct_str = f"{r['diff_pct']:.4f}%" if r["diff_pct"] is not None else "N/A"
        status_symbol = "[✓] PASS" if r["status"] == "PASS" else "[✗] FAIL"

        row_str = (
            f"{r['label']:<30} | "
            f"{p_str:>15} | "
            f"{s_str:>15} | "
            f"{diff_str:>12} | "
            f"{diff_pct_str:>9} | "
            f"{r['tolerance']:<10} | "
            f"{status_symbol:<6}"
        )
        logger.info(row_str)

    logger.info("=" * 105)
    pass_count = sum(1 for r in records if r["status"] == "PASS")
    total_count = len(records)

    if all_passed:
        logger.info(f"OVERALL RECONCILIATION RESULT: ALL {total_count}/{total_count} CHECKS PASSED ✓")
        logger.info("Data integrity verified: Pandas data cleaning and SQL loading produce identical KPIs.")
    else:
        logger.error(f"OVERALL RECONCILIATION RESULT: {pass_count}/{total_count} CHECKS PASSED. SOME FAILED ✗")
    logger.info("=" * 105)


def export_validation_json(records: list, all_passed: bool, output_path: Path = None) -> Path:
    """Save validation results to JSON for automated verification and MCA reporting."""
    out = output_path or (PATHS["data_dir"] / "metrics_validation_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "all_passed": all_passed,
        "metrics_evaluated": len(records),
        "passed_count": sum(1 for r in records if r["status"] == "PASS"),
        "metrics": records,
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Saved machine-readable validation report to: {out}")
    return out


# ============================================================
# 5. MAIN ORCHESTRATOR
# ============================================================

def run_validation(strict: bool = False, csv_only: bool = False) -> bool:
    """
    Execute the validation audit.

    Parameters
    ----------
    strict : bool
        If True, exit with code 1 if any test fails or DB is unreachable.
    csv_only : bool
        If True, only compute and display the Pandas baseline metrics.

    Returns
    -------
    bool
        True if validation passed, False otherwise.
    """
    logger.info("=" * 60)
    logger.info("PIPELINE KPI CROSS-VALIDATION STARTED")
    logger.info("=" * 60)

    # Step 1: Compute Pandas baseline
    pandas_metrics = compute_pandas_metrics()

    if csv_only:
        logger.info("Mode: --csv-only. Skipping SQL comparison.")
        return True

    # Step 2: Query SQL database
    sql_metrics = query_sql_metrics()

    if sql_metrics is None:
        logger.warning("\n" + "!" * 75)
        logger.warning("DATABASE IS NOT REACHABLE OR NOT YET POPULATED.")
        logger.warning("Pandas baseline metrics were computed successfully (shown above).")
        logger.warning("To complete the full SQL reconciliation audit:")
        logger.warning("  1. Verify MySQL / PostgreSQL is running and .env is configured.")
        logger.warning("  2. Load database tables:")
        logger.warning("     python python/load_database.py --create-tables")
        logger.warning("  3. Re-run validation:")
        logger.warning("     python python/validate_metrics.py")
        logger.warning("!" * 75 + "\n")

        if strict:
            logger.error("Strict mode enabled: Exiting with status 1 due to missing SQL data.")
            sys.exit(1)
        return False

    # Step 3: Compare metrics
    all_passed, records = compare_metrics(pandas_metrics, sql_metrics)

    # Step 4: Display table
    print_comparison_table(records, all_passed)

    # Step 5: Export JSON report
    export_validation_json(records, all_passed)

    if strict and not all_passed:
        logger.error("Strict mode enabled: One or more KPI checks failed.")
        sys.exit(1)

    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cross-validate Pandas CSV metrics against SQL database fact_sales."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero exit code if validation fails or DB is missing.",
    )
    parser.add_argument(
        "--csv-only",
        action="store_true",
        help="Compute and display Pandas baseline metrics only (no database required).",
    )
    args = parser.parse_args()

    success = run_validation(strict=args.strict, csv_only=args.csv_only)
    sys.exit(0 if success else (1 if args.strict else 0))
