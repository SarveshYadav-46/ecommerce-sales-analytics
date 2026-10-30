"""
load_database.py — Idempotent Database Loader
================================================
Reads cleaned CSVs, builds dimension tables, and loads the star schema
into MySQL or PostgreSQL via SQLAlchemy 2.

Idempotency: every run truncates all tables (facts first, then dims)
before reloading. Re-runs never duplicate data.

Usage:
    cd ecommerce-sales-analytics
    python python/load_database.py

Prerequisites:
    1. Database exists        → run sql/create_database.sql
    2. Tables exist           → run sql/create_tables.sql  (or use --create-tables flag)
    3. CSVs exist             → run python/clean_data.py
    4. .env has credentials   → copy .env.example to .env
"""

import sys
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text, inspect

from config import PATHS, get_db_url, get_db_name, setup_logging

logger = setup_logging("load_database")

# Chunk size for bulk inserts (rows per batch)
CHUNK_SIZE = 5000


# ============================================================
# 1. READ CLEANED CSVs
# ============================================================

def read_cleaned_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load cleaned_sales.csv and returns_analysis.csv.
    Exits if files are missing.
    """
    sales_path = PATHS["cleaned_sales_csv"]
    returns_path = PATHS["returns_csv"]

    for path, name in [(sales_path, "cleaned_sales.csv"), (returns_path, "returns_analysis.csv")]:
        if not path.exists():
            logger.error(f"{name} not found at {path}")
            logger.error("Run clean_data.py first.")
            sys.exit(1)

    sales_df = pd.read_csv(sales_path, parse_dates=["invoice_date"])
    returns_df = pd.read_csv(returns_path, parse_dates=["invoice_date"])

    logger.info(f"Loaded cleaned_sales.csv    : {len(sales_df):,} rows")
    logger.info(f"Loaded returns_analysis.csv  : {len(returns_df):,} rows")

    return sales_df, returns_df


# ============================================================
# 2. BUILD DIMENSION TABLES
# ============================================================

def build_dim_date(sales_df: pd.DataFrame, returns_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the date dimension from all unique dates in both CSVs.

    Columns: date_key (YYYYMMDD int), full_date, year, month,
             quarter, year_month, day_of_week, day_name.
    """
    logger.info("Building dim_date")

    # Combine all dates from both datasets
    all_dates = pd.concat([
        sales_df["invoice_date"].dropna(),
        returns_df["invoice_date"].dropna(),
    ])

    # Extract unique calendar dates (drop time component)
    unique_dates = all_dates.dt.date.unique()
    unique_dates = pd.to_datetime(sorted(unique_dates))

    dim = pd.DataFrame({"full_date": unique_dates})
    dim["date_key"] = dim["full_date"].dt.strftime("%Y%m%d").astype(int)
    dim["year"] = dim["full_date"].dt.year
    dim["month"] = dim["full_date"].dt.month
    dim["quarter"] = dim["full_date"].dt.quarter
    dim["year_month"] = dim["full_date"].dt.strftime("%Y-%m")
    dim["day_of_week"] = dim["full_date"].dt.dayofweek  # 0=Mon, 6=Sun
    dim["day_name"] = dim["full_date"].dt.day_name()

    # Ensure full_date is date-only (no time)
    dim["full_date"] = dim["full_date"].dt.date

    logger.info(f"  dim_date: {len(dim):,} unique dates")
    return dim


def build_dim_products(sales_df: pd.DataFrame, returns_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the product dimension from all unique stock_codes.
    Uses the most common non-null description for each stock_code.
    """
    logger.info("Building dim_products")

    all_products = pd.concat([
        sales_df[["stock_code", "description"]],
        returns_df[["stock_code", "description"]],
    ], ignore_index=True)

    # For each stock_code, pick the most frequent non-null description
    def best_description(group):
        non_null = group.dropna()
        if len(non_null) == 0:
            return None
        return non_null.mode().iloc[0]

    dim = (
        all_products
        .groupby("stock_code")["description"]
        .agg(best_description)
        .reset_index()
    )

    logger.info(f"  dim_products: {len(dim):,} unique stock codes")
    return dim


def build_dim_customers(sales_df: pd.DataFrame, returns_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the customer dimension from all unique non-null customer_ids.
    Uses the most common country for each customer.
    Anonymous (NULL customer_id) rows are excluded.
    """
    logger.info("Building dim_customers")

    all_customers = pd.concat([
        sales_df[["customer_id", "country"]],
        returns_df[["customer_id", "country"]],
    ], ignore_index=True)

    # Drop anonymous customers
    all_customers = all_customers.dropna(subset=["customer_id"])
    all_customers["customer_id"] = all_customers["customer_id"].astype(int)

    # Most common country per customer
    def best_country(group):
        non_null = group.dropna()
        if len(non_null) == 0:
            return None
        return non_null.mode().iloc[0]

    dim = (
        all_customers
        .groupby("customer_id")["country"]
        .agg(best_country)
        .reset_index()
    )

    logger.info(f"  dim_customers: {len(dim):,} unique customers")
    return dim


# ============================================================
# 3. PREPARE FACT TABLES
# ============================================================

def compute_date_key(df: pd.DataFrame) -> pd.Series:
    """Convert invoice_date to YYYYMMDD integer date keys."""
    return df["invoice_date"].dt.strftime("%Y%m%d").astype(int)


def prepare_fact_sales(sales_df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare the fact_sales DataFrame for database insertion.
    Selects and renames columns to match the DB schema.
    The sale_id column is auto-generated by the DB — not included here.
    """
    logger.info("Preparing fact_sales")

    fact = sales_df.copy()
    fact["date_key"] = compute_date_key(fact)

    # Handle nullable customer_id: keep NaN as None for SQL NULL
    fact["customer_id"] = fact["customer_id"].where(
        fact["customer_id"].notna(), other=None
    )

    # Select columns matching the DB schema (no sale_id — auto-increment)
    columns = [
        "invoice_no", "stock_code", "customer_id", "date_key",
        "quantity", "unit_price", "line_revenue", "country",
    ]
    fact = fact[columns]

    # Convert customer_id: pandas Int64 → python int or None
    fact["customer_id"] = fact["customer_id"].apply(
        lambda x: int(x) if pd.notna(x) else None
    )

    logger.info(f"  fact_sales prepared: {len(fact):,} rows")
    return fact


def prepare_fact_returns(returns_df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare the fact_returns DataFrame for database insertion.
    """
    logger.info("Preparing fact_returns")

    fact = returns_df.copy()
    fact["date_key"] = compute_date_key(fact)

    fact["customer_id"] = fact["customer_id"].apply(
        lambda x: int(x) if pd.notna(x) else None
    )

    columns = [
        "invoice_no", "stock_code", "customer_id", "date_key",
        "quantity", "unit_price", "line_revenue", "return_flag", "country",
    ]
    fact = fact[columns]

    logger.info(f"  fact_returns prepared: {len(fact):,} rows")
    return fact


# ============================================================
# 4. TABLE CREATION (optional — reads SQL script)
# ============================================================

def create_tables_from_sql(engine) -> None:
    """
    Execute create_tables.sql to create the star schema.
    Splits the script by semicolons and runs each statement.
    """
    sql_path = PATHS["create_tables_sql"]
    if not sql_path.exists():
        logger.error(f"SQL script not found: {sql_path}")
        sys.exit(1)

    logger.info(f"Creating tables from {sql_path.name}")

    sql_text = sql_path.read_text(encoding="utf-8")

    # Remove comment lines (-- ...) and blank lines for cleaner parsing
    lines = []
    for line in sql_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("--") or stripped == "":
            continue
        lines.append(line)

    full_sql = "\n".join(lines)

    # Split by semicolons into individual statements
    statements = [s.strip() for s in full_sql.split(";") if s.strip()]

    with engine.begin() as conn:
        for stmt in statements:
            # Skip USE statements for PostgreSQL compatibility
            if stmt.upper().startswith("USE "):
                try:
                    conn.execute(text(stmt))
                except Exception:
                    logger.info("  Skipped USE statement (PostgreSQL mode)")
                continue
            try:
                conn.execute(text(stmt))
            except Exception as e:
                logger.warning(f"  Statement warning: {e}")

    logger.info("  Tables created/verified ✓")


# ============================================================
# 5. TRUNCATE ALL TABLES (idempotent reload)
# ============================================================

def truncate_all_tables(engine, db_engine: str) -> None:
    """
    Truncate all tables before reloading.
    Facts first (they reference dims), then dims.
    Uses engine-specific FK handling.
    """
    logger.info("Truncating all tables for idempotent reload")

    with engine.begin() as conn:
        if db_engine == "mysql":
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table in ["fact_sales", "fact_returns", "dim_date", "dim_products", "dim_customers"]:
                conn.execute(text(f"TRUNCATE TABLE {table}"))
                logger.info(f"  Truncated {table}")
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        elif db_engine in ("postgresql", "postgres"):
            conn.execute(text(
                "TRUNCATE TABLE fact_sales, fact_returns, "
                "dim_date, dim_products, dim_customers CASCADE"
            ))
            logger.info("  Truncated all tables (CASCADE)")


# ============================================================
# 6. LOAD DATA INTO TABLES
# ============================================================

def load_table(
    engine,
    df: pd.DataFrame,
    table_name: str,
    chunksize: int = CHUNK_SIZE,
) -> int:
    """
    Insert a DataFrame into a database table using pandas to_sql.

    Returns the number of rows inserted.
    """
    logger.info(f"  Loading {table_name}: {len(df):,} rows (chunksize={chunksize})")

    df.to_sql(
        name=table_name,
        con=engine,
        if_exists="append",    # Table already exists (truncated)
        index=False,
        chunksize=chunksize,
        method="multi",        # Batch INSERT for performance
    )

    logger.info(f"  {table_name} loaded ✓")
    return len(df)


# ============================================================
# 7. VERIFY ROW COUNTS
# ============================================================

def verify_load(engine, expected: dict) -> bool:
    """
    Compare actual table row counts against expected counts.
    Returns True if all match.
    """
    logger.info("Verifying row counts")

    all_pass = True
    with engine.connect() as conn:
        for table_name, expected_count in expected.items():
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            actual_count = result.scalar()
            match = actual_count == expected_count
            status = "PASS ✓" if match else "FAIL ✗"
            logger.info(
                f"  {table_name:<16} expected={expected_count:>8,}  "
                f"actual={actual_count:>8,}  {status}"
            )
            if not match:
                all_pass = False

        # Revenue cross-check
        result = conn.execute(text(
            "SELECT ROUND(SUM(line_revenue), 2) FROM fact_sales"
        ))
        db_revenue = float(result.scalar() or 0)
        logger.info(f"\n  DB total revenue : {db_revenue:>14,.2f}")

    return all_pass


# ============================================================
# 8. CSV IMPORT ALTERNATIVES
# ============================================================

def print_csv_import_alternatives() -> None:
    """Print alternative CSV import commands for MySQL and PostgreSQL."""
    print("\n" + "=" * 65)
    print("  ALTERNATIVE: Direct CSV Import (bypass Python loader)")
    print("=" * 65)

    print("""
  ── MySQL (LOAD DATA INFILE) ──
  -- Must enable local_infile on both client and server:
  --   SET GLOBAL local_infile = 1;

  LOAD DATA LOCAL INFILE 'data/cleaned_sales.csv'
  INTO TABLE fact_sales
  FIELDS TERMINATED BY ','
  ENCLOSED BY '"'
  LINES TERMINATED BY '\\n'
  IGNORE 1 ROWS
  (invoice_no, stock_code, @desc, quantity, @inv_date,
   unit_price, @cust_id, country, line_revenue,
   @year, @month, @quarter, @ym)
  SET date_key   = DATE_FORMAT(STR_TO_DATE(@inv_date, '%Y-%m-%d'), '%Y%m%d'),
      customer_id = NULLIF(@cust_id, '');

  ── PostgreSQL (COPY) ──
  -- Connect to the database first, then:
  \\COPY fact_sales(invoice_no, stock_code, customer_id, date_key,
                   quantity, unit_price, line_revenue, country)
  FROM PROGRAM 'python3 -c "
    import pandas as pd
    df = pd.read_csv(''data/cleaned_sales.csv'', parse_dates=[''invoice_date''])
    df[''date_key''] = df[''invoice_date''].dt.strftime(''%Y%m%d'').astype(int)
    cols = [''invoice_no'',''stock_code'',''customer_id'',''date_key'',
            ''quantity'',''unit_price'',''line_revenue'',''country'']
    df[cols].to_csv(''/dev/stdout'', index=False, header=False)
  "'
  WITH (FORMAT CSV);
    """)
    print("=" * 65)


# ============================================================
# MAIN
# ============================================================

def main():
    """Execute the full database load pipeline."""
    parser = argparse.ArgumentParser(
        description="Load cleaned CSVs into the star-schema database."
    )
    parser.add_argument(
        "--create-tables",
        action="store_true",
        help="Execute create_tables.sql before loading data.",
    )
    parser.add_argument(
        "--show-csv-import",
        action="store_true",
        help="Print alternative CSV import commands and exit.",
    )
    args = parser.parse_args()

    if args.show_csv_import:
        print_csv_import_alternatives()
        return

    logger.info("=" * 65)
    logger.info("  DATABASE LOADER — START")
    logger.info("=" * 65)

    # --- Connect ---
    import os
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT := PATHS["project_root"] / ".env")

    db_engine_type = os.getenv("DB_ENGINE", "mysql").lower().strip()
    db_url = get_db_url(include_db=True)

    # Mask password in log output
    masked_url = db_url.split("@")
    logger.info(f"  DB engine : {db_engine_type}")
    logger.info(f"  DB target : ***@{masked_url[-1]}" if len(masked_url) > 1 else "  DB target : (connected)")

    engine = create_engine(db_url, echo=False)

    # Test connection
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("  Connection successful ✓")
    except Exception as e:
        logger.error(f"  Connection failed: {e}")
        logger.error("  Check your .env credentials and ensure the DB server is running.")
        sys.exit(1)

    # --- Optionally create tables ---
    if args.create_tables:
        create_tables_from_sql(engine)

    # --- Verify tables exist ---
    inspector = inspect(engine)
    required_tables = ["dim_date", "dim_products", "dim_customers", "fact_sales", "fact_returns"]
    existing_tables = inspector.get_table_names()
    missing = [t for t in required_tables if t not in existing_tables]

    if missing:
        logger.error(f"  Missing tables: {missing}")
        logger.error(
            "  Run: mysql -u root -p ecommerce_analytics < sql/create_tables.sql\n"
            "  Or use: python python/load_database.py --create-tables"
        )
        sys.exit(1)

    logger.info(f"  All {len(required_tables)} tables found ✓")

    # --- Read CSVs ---
    sales_df, returns_df = read_cleaned_data()

    # --- Build dimensions ---
    dim_date_df = build_dim_date(sales_df, returns_df)
    dim_products_df = build_dim_products(sales_df, returns_df)
    dim_customers_df = build_dim_customers(sales_df, returns_df)

    # --- Prepare facts ---
    fact_sales_df = prepare_fact_sales(sales_df)
    fact_returns_df = prepare_fact_returns(returns_df)

    # --- Truncate (idempotent) ---
    truncate_all_tables(engine, db_engine_type)

    # --- Load dimensions FIRST (referenced by facts) ---
    logger.info("Loading dimension tables")
    load_table(engine, dim_date_df, "dim_date")
    load_table(engine, dim_products_df, "dim_products")
    load_table(engine, dim_customers_df, "dim_customers")

    # --- Load facts ---
    logger.info("Loading fact tables")
    load_table(engine, fact_sales_df, "fact_sales")
    load_table(engine, fact_returns_df, "fact_returns")

    # --- Verify ---
    expected = {
        "dim_date": len(dim_date_df),
        "dim_products": len(dim_products_df),
        "dim_customers": len(dim_customers_df),
        "fact_sales": len(fact_sales_df),
        "fact_returns": len(fact_returns_df),
    }

    all_pass = verify_load(engine, expected)

    # --- Cross-check CSV revenue vs DB revenue ---
    csv_revenue = round(float(sales_df["line_revenue"].sum()), 2)
    with engine.connect() as conn:
        db_revenue = float(
            conn.execute(text("SELECT ROUND(SUM(line_revenue), 2) FROM fact_sales")).scalar() or 0
        )

    rev_match = abs(csv_revenue - db_revenue) < 0.01
    rev_status = "PASS ✓" if rev_match else "FAIL ✗"
    logger.info(f"\n  Revenue cross-check:")
    logger.info(f"    CSV total  : {csv_revenue:>14,.2f}")
    logger.info(f"    DB total   : {db_revenue:>14,.2f}")
    logger.info(f"    Match      : {rev_status}")

    # --- Summary ---
    logger.info("\n" + "=" * 65)
    if all_pass and rev_match:
        logger.info("  DATABASE LOADER — COMPLETE ✓  (all checks passed)")
    else:
        logger.warning("  DATABASE LOADER — COMPLETE WITH WARNINGS ⚠")
    logger.info("=" * 65)

    # --- Print verification queries ---
    print("\n  Run these verification queries in your SQL client:")
    print("  " + "-" * 55)
    print("""
  -- Row counts
  SELECT 'dim_date'      AS tbl, COUNT(*) AS rows FROM dim_date
  UNION ALL
  SELECT 'dim_products',         COUNT(*)         FROM dim_products
  UNION ALL
  SELECT 'dim_customers',        COUNT(*)         FROM dim_customers
  UNION ALL
  SELECT 'fact_sales',           COUNT(*)         FROM fact_sales
  UNION ALL
  SELECT 'fact_returns',         COUNT(*)         FROM fact_returns;

  -- Revenue check
  SELECT ROUND(SUM(line_revenue), 2) AS total_revenue
  FROM fact_sales;

  -- Distinct invoices
  SELECT COUNT(DISTINCT invoice_no) AS unique_orders
  FROM fact_sales;

  -- Customer count (identified only)
  SELECT COUNT(DISTINCT customer_id) AS unique_customers
  FROM fact_sales
  WHERE customer_id IS NOT NULL;

  -- Anonymous sales
  SELECT COUNT(*) AS anonymous_rows,
         ROUND(SUM(line_revenue), 2) AS anonymous_revenue
  FROM fact_sales
  WHERE customer_id IS NULL;
    """)


if __name__ == "__main__":
    main()
