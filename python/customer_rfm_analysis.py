"""
customer_rfm_analysis.py — Customer RFM Segmentation & Scoring Pipeline
========================================================================
Performs Recency, Frequency, and Monetary (RFM) analysis on eligible sales
data from cleaned_sales.csv. Assigns quintile scores (1–5) and maps customers
to 10 distinct, actionable business segments using analytical heuristics.

Output:
    - data/customer_rfm.csv
    - Optional database load into ecommerce_analytics.customer_rfm

Usage:
    cd ecommerce-sales-analytics
    python python/customer_rfm_analysis.py
    python python/customer_rfm_analysis.py --load-db
    python python/customer_rfm_analysis.py --summary
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from config import PATHS, get_db_url, setup_logging

logger = setup_logging("customer_rfm_analysis")


# ============================================================
# 1. LOAD CLEANED SALES DATA
# ============================================================

def load_clean_sales_data(filepath: Path = None) -> pd.DataFrame:
    """
    Load cleaned_sales.csv and validate essential columns.

    Parameters
    ----------
    filepath : Path, optional
        Path to cleaned_sales.csv. Defaults to PATHS["cleaned_sales_csv"].

    Returns
    -------
    pd.DataFrame
        Loaded sales DataFrame.
    """
    path = filepath or PATHS["cleaned_sales_csv"]
    if not path.exists():
        logger.error(f"Cleaned sales file not found: {path}")
        logger.error("Run python/clean_data.py first to generate cleaned_sales.csv.")
        sys.exit(1)

    logger.info(f"Loading cleaned sales data from: {path}")
    df = pd.read_csv(
        path,
        parse_dates=["invoice_date"],
        dtype={
            "invoice_no": str,
            "stock_code": str,
            "customer_id": "Int64",
            "country": str,
            "quantity": int,
            "unit_price": float,
            "line_revenue": float,
        },
    )
    logger.info(f"Loaded {len(df):,} total sales records.")
    return df


# ============================================================
# 2. COMPUTE RAW RFM METRICS PER CUSTOMER
# ============================================================

def compute_rfm_metrics(
    df: pd.DataFrame, reference_date: datetime = None
) -> pd.DataFrame:
    """
    Aggregate transactional sales into customer-level RFM metrics.

    Conventions:
      • Anonymous customers (customer_id IS NULL) are excluded because
        individual behavior cannot be tracked without an identifier.
      • Reference date defaults to max(invoice_date) + 1 day so that
        the most recent purchaser has a recency of 1 day (not 0).
      • Recency: Days between reference date and customer's latest purchase.
      • Frequency: Total distinct invoice_no transactions per customer.
      • Monetary: Total gross sales (line_revenue) per customer.

    Parameters
    ----------
    df : pd.DataFrame
        Cleaned sales DataFrame.
    reference_date : datetime, optional
        Analysis reference date.

    Returns
    -------
    pd.DataFrame
        Customer-level DataFrame with raw R, F, M values.
    """
    logger.info("Computing raw RFM metrics per identified customer...")

    # Filter out anonymous transactions
    identified_df = df[df["customer_id"].notna()].copy()
    identified_df["customer_id"] = identified_df["customer_id"].astype(int)

    anon_count = len(df) - len(identified_df)
    logger.info(
        f"Filtered out {anon_count:,} anonymous rows (customer_id IS NULL). "
        f"Proceeding with {len(identified_df):,} identified rows."
    )

    # Establish reference date
    max_invoice_date = identified_df["invoice_date"].max()
    if reference_date is None:
        # Standard retail practice: max transaction date + 1 day
        reference_date = max_invoice_date + pd.Timedelta(days=1)

    logger.info(f"Max transaction date in dataset : {max_invoice_date.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"RFM analysis reference date    : {reference_date.strftime('%Y-%m-%d %H:%M:%S')}")

    # Aggregations per customer
    rfm_grouped = identified_df.groupby("customer_id").agg(
        last_purchase_date=("invoice_date", "max"),
        first_purchase_date=("invoice_date", "min"),
        frequency_orders=("invoice_no", "nunique"),
        monetary_revenue=("line_revenue", "sum"),
        total_units=("quantity", "sum"),
        # Primary country: most frequent country recorded
        country=("country", lambda x: x.mode().iloc[0] if not x.mode().empty else "Unknown"),
    ).reset_index()

    # Calculate Recency in days
    rfm_grouped["recency_days"] = (
        reference_date - rfm_grouped["last_purchase_date"]
    ).dt.days

    # Round monetary figures
    rfm_grouped["monetary_revenue"] = rfm_grouped["monetary_revenue"].round(2)

    logger.info(f"Successfully computed RFM metrics for {len(rfm_grouped):,} unique identified customers.")
    return rfm_grouped


# ============================================================
# 3. ASSIGN RFM QUINTILE SCORES (1 to 5)
# ============================================================

def assign_rfm_scores(rfm_df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign quintile scores (1 to 5) for Recency, Frequency, and Monetary.

    Scoring Logic:
      • Recency (R): Lower recency_days = Higher score (5 = most recent, 1 = oldest).
      • Frequency (F): Higher frequency_orders = Higher score (5 = most frequent, 1 = least).
      • Monetary (M): Higher monetary_revenue = Higher score (5 = highest spend, 1 = lowest).

    Tie-breaking:
      In retail data, frequency often has many identical low values (e.g. F=1).
      We use rank(method='first') before binning with pd.qcut to guarantee
      clean 5-tier quintiles without empty bin errors.

    Parameters
    ----------
    rfm_df : pd.DataFrame
        Customer DataFrame with recency_days, frequency_orders, monetary_revenue.

    Returns
    -------
    pd.DataFrame
        DataFrame with r_score, f_score, m_score, rfm_score, and rfm_total_score.
    """
    logger.info("Assigning 1-5 quintile scores using rank-based binning...")
    df = rfm_df.copy()

    # Recency: lowest days gets highest rank when ascending=False -> score 5
    r_rank = df["recency_days"].rank(method="first", ascending=False)
    df["r_score"] = pd.qcut(r_rank, q=5, labels=[1, 2, 3, 4, 5]).astype(int)

    # Frequency: highest order count gets highest rank -> score 5
    f_rank = df["frequency_orders"].rank(method="first", ascending=True)
    df["f_score"] = pd.qcut(f_rank, q=5, labels=[1, 2, 3, 4, 5]).astype(int)

    # Monetary: highest revenue gets highest rank -> score 5
    m_rank = df["monetary_revenue"].rank(method="first", ascending=True)
    df["m_score"] = pd.qcut(m_rank, q=5, labels=[1, 2, 3, 4, 5]).astype(int)

    # Composite RFM Score string (e.g. '555', '111') and total numerical score (3-15)
    df["rfm_score"] = (
        df["r_score"].astype(str)
        + df["f_score"].astype(str)
        + df["m_score"].astype(str)
    )
    df["rfm_total_score"] = df["r_score"] + df["f_score"] + df["m_score"]

    logger.info("Assigned R, F, and M scores successfully.")
    return df


# ============================================================
# 4. MAP TO 10 ACTIONABLE BUSINESS SEGMENTS
# ============================================================

def classify_rfm_segment(r: int, f: int, m: int) -> str:
    """
    Classify a customer into one of 10 business heuristic segments
    based on individual R, F, and M scores.

    Analytical Heuristic Segments:
      1. Champions: Top recency, top frequency, top spenders.
      2. Loyal Customers: High frequency and high spenders with strong recency.
      3. Cant Lose Them: Previously top tier (F, M >= 4) but have lapsed (R <= 2).
      4. At Risk: Above-average past spenders/repeaters who haven't bought recently.
      5. Potential Loyalists: Recent buyers with 2-3 orders; receptive to engagement.
      6. New Customers: Recent buyers who have only made 1 purchase so far.
      7. Promising: Moderate recency with low frequency.
      8. About to Sleep: Below average recency with low frequency.
      9. Lost: Oldest recency, single transaction, lowest spend.
      10. Need Attention: Medium recency, frequency, and spend not fitting other rules.

    Parameters
    ----------
    r, f, m : int
        Individual integer scores (1 to 5).

    Returns
    -------
    str
        Segment designation.
    """
    # 1. Champions: The best customers
    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"

    # 2. Loyal Customers: Consistent repeat purchasers
    if r >= 3 and f >= 3 and m >= 3:
        return "Loyal Customers"

    # 3. Cant Lose Them: Used to be frequent and big spenders, now inactive
    if r <= 2 and f >= 4 and m >= 4:
        return "Cant Lose Them"

    # 4. At Risk: Valuable repeat buyers whose activity has cooled down
    if r <= 2 and f >= 3 and m >= 3:
        return "At Risk"

    # 5. Potential Loyalists: Recent buyers with 2–3 purchases
    if r >= 4 and f in (2, 3):
        return "Potential Loyalists"

    # 6. New Customers: High recency, but only 1 purchase
    if r >= 4 and f == 1:
        return "New Customers"

    # 7. Promising: Average recency with 1–2 orders
    if r == 3 and f in (1, 2):
        return "Promising"

    # 8. About to Sleep: Below average recency and low order count
    if r == 2 and f in (1, 2):
        return "About to Sleep"

    # 9. Lost: Inactive for longest time, 1-2 orders, low spend
    if r == 1 and f <= 2:
        return "Lost"

    # 10. Fallback / Middle-ground
    return "Need Attention"


def assign_rfm_segments(rfm_df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply segment mapping to each customer in the RFM DataFrame.

    Parameters
    ----------
    rfm_df : pd.DataFrame
        DataFrame with r_score, f_score, m_score.

    Returns
    -------
    pd.DataFrame
        DataFrame with added 'rfm_segment' column.
    """
    logger.info("Mapping customers to 10 analytical heuristic segments...")
    df = rfm_df.copy()

    df["rfm_segment"] = [
        classify_rfm_segment(r, f, m)
        for r, f, m in zip(df["r_score"], df["f_score"], df["m_score"])
    ]

    return df


# ============================================================
# 5. COMPUTE SEGMENT SUMMARY STATISTICS
# ============================================================

def compute_segment_summary(rfm_df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate an executive summary table aggregated by RFM segment.

    Parameters
    ----------
    rfm_df : pd.DataFrame
        DataFrame containing rfm_segment and metrics.

    Returns
    -------
    pd.DataFrame
        Aggregated summary table sorted by total revenue descending.
    """
    total_customers = len(rfm_df)
    total_rev = rfm_df["monetary_revenue"].sum()

    summary = (
        rfm_df.groupby("rfm_segment")
        .agg(
            customer_count=("customer_id", "count"),
            total_revenue=("monetary_revenue", "sum"),
            avg_recency_days=("recency_days", "mean"),
            avg_frequency_orders=("frequency_orders", "mean"),
            avg_monetary_revenue=("monetary_revenue", "mean"),
        )
        .reset_index()
    )

    summary["pct_of_customers"] = (
        summary["customer_count"] / total_customers * 100
    ).round(2)
    summary["pct_of_revenue"] = (
        summary["total_revenue"] / total_rev * 100
    ).round(2)
    summary["avg_aov"] = (
        summary["avg_monetary_revenue"] / summary["avg_frequency_orders"]
    ).round(2)

    # Round display columns
    summary["total_revenue"] = summary["total_revenue"].round(2)
    summary["avg_recency_days"] = summary["avg_recency_days"].round(1)
    summary["avg_frequency_orders"] = summary["avg_frequency_orders"].round(1)
    summary["avg_monetary_revenue"] = summary["avg_monetary_revenue"].round(2)

    # Sort by total revenue descending
    summary = summary.sort_values(by="total_revenue", ascending=False).reset_index(drop=True)
    return summary


def display_segment_summary(summary: pd.DataFrame) -> None:
    """Format and print the RFM segment summary table to console and logger."""
    logger.info("\n" + "=" * 90)
    logger.info("RFM CUSTOMER SEGMENTATION EXECUTIVE SUMMARY")
    logger.info("=" * 90)

    header = (
        f"{'Segment':<22} | {'Customers':>9} | {'% Cust':>7} | "
        f"{'Revenue':>13} | {'% Rev':>6} | {'Avg Rec':>7} | {'Avg Freq':>8} | {'Avg Mon':>10}"
    )
    logger.info(header)
    logger.info("-" * len(header))

    for _, row in summary.iterrows():
        line = (
            f"{row['rfm_segment']:<22} | "
            f"{row['customer_count']:>9,d} | "
            f"{row['pct_of_customers']:>6.2f}% | "
            f"${row['total_revenue']:>12,.2f} | "
            f"{row['pct_of_revenue']:>5.2f}% | "
            f"{row['avg_recency_days']:>7.1f} | "
            f"{row['avg_frequency_orders']:>8.1f} | "
            f"${row['avg_monetary_revenue']:>9,.2f}"
        )
        logger.info(line)

    logger.info("=" * 90)


# ============================================================
# 6. EXPORT TO CSV
# ============================================================

def export_rfm_csv(rfm_df: pd.DataFrame, output_path: Path = None) -> Path:
    """
    Export the enriched RFM DataFrame to customer_rfm.csv.

    Columns exported:
      customer_id, country, first_purchase_date, last_purchase_date,
      recency_days, frequency_orders, monetary_revenue, total_units,
      r_score, f_score, m_score, rfm_score, rfm_total_score, rfm_segment.
    """
    out = output_path or PATHS["rfm_csv"]
    out.parent.mkdir(parents=True, exist_ok=True)

    export_cols = [
        "customer_id",
        "country",
        "first_purchase_date",
        "last_purchase_date",
        "recency_days",
        "frequency_orders",
        "monetary_revenue",
        "total_units",
        "r_score",
        "f_score",
        "m_score",
        "rfm_score",
        "rfm_total_score",
        "rfm_segment",
    ]

    rfm_df[export_cols].to_csv(out, index=False)
    logger.info(f"Successfully exported RFM analysis to: {out} ({len(rfm_df):,} rows)")
    return out


# ============================================================
# 7. OPTIONAL LOAD TO DATABASE
# ============================================================

def load_rfm_to_database(rfm_df: pd.DataFrame) -> None:
    """
    Optionally load the customer_rfm table into the SQL database.
    Creates table if it does not exist, and replaces contents idempotently.
    """
    logger.info("Attempting to load RFM segments into SQL database...")
    try:
        url = get_db_url()
        engine = create_engine(url)

        with engine.connect() as conn:
            # Check table existence or create DDL
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS customer_rfm (
                customer_id         INT PRIMARY KEY,
                country             VARCHAR(50),
                first_purchase_date DATETIME,
                last_purchase_date  DATETIME,
                recency_days        INT NOT NULL,
                frequency_orders    INT NOT NULL,
                monetary_revenue    DECIMAL(12,2) NOT NULL,
                total_units         INT NOT NULL,
                r_score             TINYINT NOT NULL,
                f_score             TINYINT NOT NULL,
                m_score             TINYINT NOT NULL,
                rfm_score           VARCHAR(5) NOT NULL,
                rfm_total_score     SMALLINT NOT NULL,
                rfm_segment         VARCHAR(30) NOT NULL,
                INDEX idx_rfm_segment (rfm_segment),
                INDEX idx_rfm_score (rfm_score)
            );
            """
            conn.execute(text(create_table_sql))
            conn.execute(text("TRUNCATE TABLE customer_rfm;"))
            conn.commit()

        # Insert records via pandas
        load_df = rfm_df[[
            "customer_id", "country", "first_purchase_date", "last_purchase_date",
            "recency_days", "frequency_orders", "monetary_revenue", "total_units",
            "r_score", "f_score", "m_score", "rfm_score", "rfm_total_score", "rfm_segment"
        ]].copy()

        load_df.to_sql(
            "customer_rfm",
            con=engine,
            if_exists="append",
            index=False,
            chunksize=2000,
        )
        logger.info(f"Loaded {len(load_df):,} customer RFM rows into database table 'customer_rfm' ✓")

    except Exception as e:
        logger.warning(f"Could not load RFM to database: {e}")
        logger.warning("customer_rfm.csv remains available for Tableau and manual analysis.")


# ============================================================
# 8. MAIN ORCHESTRATOR
# ============================================================

def run_rfm_pipeline(load_db: bool = False, print_summary: bool = True) -> pd.DataFrame:
    """
    Execute the end-to-end customer RFM analysis pipeline.

    Steps:
      1. Load cleaned sales CSV.
      2. Compute raw RFM metrics.
      3. Assign 1–5 quintile scores.
      4. Map customers to 10 analytical heuristic segments.
      5. Compute and print segment summary statistics.
      6. Export to data/customer_rfm.csv.
      7. Optionally load to SQL database.

    Returns
    -------
    pd.DataFrame
        Enriched RFM DataFrame.
    """
    logger.info("=" * 60)
    logger.info("CUSTOMER RFM SEGMENTATION PIPELINE STARTED")
    logger.info("=" * 60)

    # 1. Load data
    sales_df = load_clean_sales_data()

    # 2. Raw metrics
    raw_rfm = compute_rfm_metrics(sales_df)

    # 3. Quintile scores
    scored_rfm = assign_rfm_scores(raw_rfm)

    # 4. Heuristic segments
    segmented_rfm = assign_rfm_segments(scored_rfm)

    # 5. Segment summary
    summary_df = compute_segment_summary(segmented_rfm)
    if print_summary:
        display_segment_summary(summary_df)

    # 6. CSV Export
    export_rfm_csv(segmented_rfm)

    # 7. Optional DB load
    if load_db:
        load_rfm_to_database(segmented_rfm)

    logger.info("CUSTOMER RFM SEGMENTATION PIPELINE COMPLETED ✓")
    logger.info("=" * 60)
    return segmented_rfm


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run customer RFM segmentation on cleaned sales data."
    )
    parser.add_argument(
        "--load-db",
        action="store_true",
        help="Load customer_rfm table into the SQL database.",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Suppress console summary table output.",
    )
    args = parser.parse_args()

    run_rfm_pipeline(
        load_db=args.load_db,
        print_summary=not args.no_summary,
    )
