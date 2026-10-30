"""
test_pipeline.py — Comprehensive Test Suite for E-Commerce Sales Intelligence
=============================================================================
Automated test suite verifying data engineering, star-schema warehouse integrity,
RFM segmentation logic, and mathematical cross-validation against tolerances.

Run with:
    cd ecommerce-sales-analytics
    pytest -v tests/test_pipeline.py
"""

import sys
from pathlib import Path

import pytest
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text, inspect

# Ensure python/ is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python"))

from config import PATHS, get_db_url


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(scope="session")
def db_engine():
    """Create a SQLAlchemy engine connected to the ecommerce_analytics database."""
    url = get_db_url(include_db=True)
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def cleaned_sales_df():
    """Load cleaned_sales.csv into a DataFrame."""
    path = PATHS["cleaned_sales_csv"]
    assert path.exists(), f"cleaned_sales.csv missing at {path}"
    df = pd.read_csv(path, dtype={"invoice_no": str, "stock_code": str, "customer_id": "Int64"})
    return df


@pytest.fixture(scope="session")
def returns_df():
    """Load returns_analysis.csv into a DataFrame."""
    path = PATHS["returns_csv"]
    assert path.exists(), f"returns_analysis.csv missing at {path}"
    df = pd.read_csv(path, dtype={"invoice_no": str, "stock_code": str, "customer_id": "Int64"})
    return df


@pytest.fixture(scope="session")
def rfm_df():
    """Load customer_rfm.csv into a DataFrame."""
    path = PATHS["rfm_csv"]
    assert path.exists(), f"customer_rfm.csv missing at {path}"
    df = pd.read_csv(path)
    return df


# ============================================================
# 1. DATA QUALITY & CONSERVATION TESTS
# ============================================================

def test_data_files_exist():
    """Verify all primary generated data artifacts exist on disk."""
    assert PATHS["raw_excel"].exists(), "Online Retail.xlsx raw dataset missing."
    assert PATHS["cleaned_sales_csv"].exists(), "cleaned_sales.csv missing."
    assert PATHS["returns_csv"].exists(), "returns_analysis.csv missing."
    assert PATHS["rfm_csv"].exists(), "customer_rfm.csv missing."
    assert PATHS["quality_report_json"].exists(), "data_quality_report.json missing."


def test_row_conservation(cleaned_sales_df, returns_df):
    """
    Verify complete row conservation:
    raw_rows (541,909) - duplicates (5,268) == sales (524,878) + returns (11,763) == 536,641.
    """
    total_retained = len(cleaned_sales_df) + len(returns_df)
    assert total_retained == 536641, f"Expected 536,641 retained rows, got {total_retained:,}"
    assert len(cleaned_sales_df) == 524878, f"Expected 524,878 sales, got {len(cleaned_sales_df):,}"
    assert len(returns_df) == 11763, f"Expected 11,763 returns, got {len(returns_df):,}"


def test_sales_partition_integrity(cleaned_sales_df):
    """Verify that eligible sales contain strictly valid quantities, prices, and non-C invoices."""
    # 1. No C-invoices
    c_invoices = cleaned_sales_df["invoice_no"].str.startswith("C", na=False).sum()
    assert c_invoices == 0, f"Found {c_invoices} C-invoices in cleaned_sales.csv!"

    # 2. Quantity strictly positive
    invalid_qty = (cleaned_sales_df["quantity"] <= 0).sum()
    assert invalid_qty == 0, f"Found {invalid_qty} non-positive quantities in cleaned_sales.csv!"

    # 3. Unit price strictly positive
    invalid_price = (cleaned_sales_df["unit_price"] <= 0).sum()
    assert invalid_price == 0, f"Found {invalid_price} non-positive prices in cleaned_sales.csv!"

    # 4. Line revenue matches quantity * unit_price
    expected_rev = (cleaned_sales_df["quantity"] * cleaned_sales_df["unit_price"]).round(2)
    diff = np.abs(cleaned_sales_df["line_revenue"] - expected_rev).max()
    assert diff < 0.01, f"Max line_revenue rounding diff is {diff}, expected < 0.01"


def test_returns_partition_integrity(returns_df):
    """Verify that returns_analysis.csv rows have return_flag populated."""
    assert returns_df["return_flag"].notna().all(), "Found null return_flag values in returns_analysis.csv"
    valid_flags = {"C_invoice|negative_quantity", "negative_quantity", "adjustment_non_positive_price"}
    actual_flags = set(returns_df["return_flag"].unique())
    assert actual_flags.issubset(valid_flags), f"Unexpected return flags found: {actual_flags - valid_flags}"


# ============================================================
# 2. DATABASE WAREHOUSE & STAR SCHEMA TESTS
# ============================================================

def test_database_tables_exist(db_engine):
    """Verify all 5 star-schema tables and customer_rfm exist in the database."""
    inspector = inspect(db_engine)
    existing_tables = set(inspector.get_table_names())
    required_tables = {"dim_date", "dim_products", "dim_customers", "fact_sales", "fact_returns", "customer_rfm"}
    missing = required_tables - existing_tables
    assert not missing, f"Missing required database tables: {missing}"


def test_database_row_counts(db_engine):
    """Verify that warehouse table row counts match expected values."""
    expected_counts = {
        "dim_date": 305,
        "dim_products": 4070,
        "dim_customers": 4372,
        "fact_sales": 524878,
        "fact_returns": 11763,
        "customer_rfm": 4338,
    }
    with db_engine.connect() as conn:
        for table, expected in expected_counts.items():
            actual = conn.execute(text(f"SELECT COUNT(*) FROM {table};")).scalar()
            assert actual == expected, f"Table {table}: expected {expected:,} rows, got {actual:,}"


def test_database_referential_integrity(db_engine):
    """Verify no orphaned foreign keys in fact_sales."""
    with db_engine.connect() as conn:
        # Check orphaned stock_code
        orphaned_products = conn.execute(text("""
            SELECT COUNT(*) FROM fact_sales f
            LEFT JOIN dim_products p ON f.stock_code = p.stock_code
            WHERE p.stock_code IS NULL;
        """)).scalar()
        assert orphaned_products == 0, f"Found {orphaned_products} orphaned stock_code rows in fact_sales!"

        # Check orphaned date_key
        orphaned_dates = conn.execute(text("""
            SELECT COUNT(*) FROM fact_sales f
            LEFT JOIN dim_date d ON f.date_key = d.date_key
            WHERE d.date_key IS NULL;
        """)).scalar()
        assert orphaned_dates == 0, f"Found {orphaned_dates} orphaned date_key rows in fact_sales!"

        # Check orphaned customer_id (for non-null customers)
        orphaned_customers = conn.execute(text("""
            SELECT COUNT(*) FROM fact_sales f
            LEFT JOIN dim_customers c ON f.customer_id = c.customer_id
            WHERE f.customer_id IS NOT NULL AND c.customer_id IS NULL;
        """)).scalar()
        assert orphaned_customers == 0, f"Found {orphaned_customers} orphaned customer_id rows in fact_sales!"


# ============================================================
# 3. RFM SEGMENTATION MODEL TESTS
# ============================================================

def test_rfm_customer_count(rfm_df):
    """Verify customer_rfm.csv has exactly 4,338 unique identified customers."""
    assert len(rfm_df) == 4338, f"Expected 4,338 customers, got {len(rfm_df)}"
    assert rfm_df["customer_id"].nunique() == 4338, "Duplicate customer_ids found in customer_rfm.csv!"


def test_rfm_scores_validity(rfm_df):
    """Verify that R, F, and M scores are strictly in {1, 2, 3, 4, 5}."""
    for score_col in ["r_score", "f_score", "m_score"]:
        unique_scores = set(rfm_df[score_col].unique())
        assert unique_scores == {1, 2, 3, 4, 5}, f"Scores in {score_col} are invalid: {unique_scores}"

    # Verify composite score format (3 digits, each 1-5)
    rfm_score_str = rfm_df["rfm_score"].astype(str)
    assert rfm_score_str.str.match(r"^[1-5]{3}$").all(), "Found invalid rfm_score strings!"


def test_rfm_segments_completeness(rfm_df):
    """Verify that all 10 heuristic segments are present without NaN values."""
    assert rfm_df["rfm_segment"].notna().all(), "Found null segment names in customer_rfm.csv!"
    expected_segments = {
        "Champions", "Loyal Customers", "Cant Lose Them", "At Risk", "Lost",
        "About to Sleep", "Promising", "Potential Loyalists", "Need Attention", "New Customers"
    }
    actual_segments = set(rfm_df["rfm_segment"].unique())
    assert actual_segments == expected_segments, f"Segment mismatch. Found: {actual_segments}"


def test_rfm_pareto_revenue(rfm_df):
    """Verify that Champions + Loyal Customers account for >75% of identified revenue."""
    top_tiers = rfm_df[rfm_df["rfm_segment"].isin(["Champions", "Loyal Customers"])]
    top_revenue = top_tiers["monetary_revenue"].sum()
    total_revenue = rfm_df["monetary_revenue"].sum()
    revenue_share = (top_revenue / total_revenue) * 100.0
    assert revenue_share > 75.0, f"Expected top tiers to generate >75% revenue, got {revenue_share:.2f}%"


# ============================================================
# 4. CROSS-VALIDATION RECONCILIATION TESTS (PANDAS vs SQL)
# ============================================================

def test_gross_revenue_reconciliation(cleaned_sales_df, db_engine):
    """Verify that Gross Revenue matches between Pandas and SQL to within 0.01%."""
    pandas_rev = round(float(cleaned_sales_df["line_revenue"].sum()), 2)
    with db_engine.connect() as conn:
        sql_rev = float(conn.execute(text("SELECT ROUND(SUM(line_revenue), 2) FROM fact_sales;")).scalar())

    assert abs(pandas_rev - sql_rev) <= 0.05, f"Revenue mismatch: Pandas={pandas_rev}, SQL={sql_rev}"
    assert pandas_rev == 10642110.80, f"Expected $10,642,110.80, got {pandas_rev}"


def test_order_count_reconciliation(cleaned_sales_df, db_engine):
    """Verify distinct invoice count matches exactly between Pandas and SQL."""
    pandas_orders = int(cleaned_sales_df["invoice_no"].nunique())
    with db_engine.connect() as conn:
        sql_orders = int(conn.execute(text("SELECT COUNT(DISTINCT invoice_no) FROM fact_sales;")).scalar())

    assert pandas_orders == sql_orders == 19960, f"Order mismatch: Pandas={pandas_orders}, SQL={sql_orders}"


def test_customer_count_reconciliation(cleaned_sales_df, db_engine):
    """Verify identified customer count matches exactly between Pandas and SQL."""
    pandas_customers = int(cleaned_sales_df["customer_id"].dropna().nunique())
    with db_engine.connect() as conn:
        sql_customers = int(conn.execute(text("""
            SELECT COUNT(DISTINCT customer_id) FROM fact_sales WHERE customer_id IS NOT NULL;
        """)).scalar())

    assert pandas_customers == sql_customers == 4338, f"Customer mismatch: Pandas={pandas_customers}, SQL={sql_customers}"


def test_unit_count_reconciliation(cleaned_sales_df, db_engine):
    """Verify total units sold matches exactly between Pandas and SQL."""
    pandas_units = int(cleaned_sales_df["quantity"].sum())
    with db_engine.connect() as conn:
        sql_units = int(conn.execute(text("SELECT SUM(quantity) FROM fact_sales;")).scalar())

    assert pandas_units == sql_units == 5572420, f"Units mismatch: Pandas={pandas_units}, SQL={sql_units}"


def test_repeat_rate_reconciliation(cleaned_sales_df, db_engine):
    """Verify customer repeat rate matches between Pandas and SQL within 0.05%."""
    cust_orders = cleaned_sales_df.dropna(subset=["customer_id"]).groupby("customer_id")["invoice_no"].nunique()
    pandas_repeat_rate = round(((cust_orders >= 2).sum() / len(cust_orders)) * 100.0, 2)

    with db_engine.connect() as conn:
        sql_repeat_rate = float(conn.execute(text("""
            WITH cust_orders AS (
                SELECT customer_id, COUNT(DISTINCT invoice_no) AS order_count
                FROM fact_sales
                WHERE customer_id IS NOT NULL
                GROUP BY customer_id
            )
            SELECT ROUND(SUM(CASE WHEN order_count >= 2 THEN 1.0 ELSE 0.0 END) / COUNT(*) * 100, 2)
            FROM cust_orders;
        """)).scalar())

    assert abs(pandas_repeat_rate - sql_repeat_rate) <= 0.05, f"Repeat rate mismatch: Pandas={pandas_repeat_rate}%, SQL={sql_repeat_rate}%"
    assert pandas_repeat_rate == 65.58, f"Expected 65.58%, got {pandas_repeat_rate}%"
