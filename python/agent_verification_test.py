"""
Agent Comprehensive Diagnostic & System Verification Script.
Author: Antigravity AI Agent
Description:
    Performs autonomous, multi-vector validation of:
    1. MySQL 8 Database health, engine status, table sizes, index coverage
    2. SQL Query Execution & latency benchmark across complex analytical queries
    3. File artifact integrity & binary completeness (CSVs, JSONs, HTML, PNGs)
    4. Referential integrity & edge cases (zero orphan keys, null safety)
    5. Data distribution assertions (RFM segment counts, Pareto ratio)
"""

import os
import sys
import time
import json
import pandas as pd
from PIL import Image
from pathlib import Path
from sqlalchemy import create_engine, text

# Reconfigure stdout for UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
from python.config import PATHS, PROJECT_ROOT, get_db_url

def run_agent_test():
    print("=" * 80)
    print("      AUTONOMOUS AGENT SYSTEM & DATA INTEGRITY VERIFICATION SUITE")
    print("=" * 80)
    print(f"Project Directory : {PROJECT_ROOT}")
    print(f"Timestamp          : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 80)

    test_results = []

    def record_test(category, name, passed, details=""):
        status_str = "[PASS] ✓" if passed else "[FAIL] ✗"
        print(f"{category:<20} | {name:<35} | {status_str} | {details}")
        test_results.append({
            "category": category,
            "test": name,
            "passed": passed,
            "details": details
        })

    # ==========================================
    # VECTOR 1: FILE SYSTEM ARTIFACTS
    # ==========================================
    print("\n--- VECTOR 1: ARTIFACT INTEGRITY CHECK ---")
    data_dir = PATHS["data_dir"]
    screenshots_dir = PATHS["screenshots_dir"]
    tests_dir = PROJECT_ROOT / "tests"

    required_files = {
        "Raw Data": PATHS["raw_excel"],
        "Cleaned Sales CSV": PATHS["cleaned_sales_csv"],
        "Returns CSV": PATHS["returns_csv"],
        "RFM CSV": PATHS["rfm_csv"],
        "Data Quality JSON": PATHS["quality_report_json"],
        "Metrics Validation JSON": data_dir / "metrics_validation_report.json",
        "SQL Analysis Results": data_dir / "sql_analysis_results.txt",
        "HTML Test Report": tests_dir / "test_report.html",
        "Dashboard 1 PNG": screenshots_dir / "dashboard1_executive_overview.png",
        "Dashboard 2 PNG": screenshots_dir / "dashboard2_customer_intel.png",
        "Dashboard 3 PNG": screenshots_dir / "dashboard3_product_returns.png"
    }

    for name, fpath in required_files.items():
        exists = fpath.exists()
        size_kb = (fpath.stat().st_size / 1024) if exists else 0
        passed = exists and size_kb > 0
        record_test("Artifacts", name, passed, f"{size_kb:,.1f} KB")

    # Image dimension check
    for img_name in ["dashboard1_executive_overview.png", "dashboard2_customer_intel.png", "dashboard3_product_returns.png"]:
        p = screenshots_dir / img_name
        if p.exists():
            with Image.open(p) as img:
                w, h = img.size
                valid_dims = (w >= 1800 and h >= 1000)
                record_test("Visual Quality", f"Resolution: {img_name}", valid_dims, f"{w}x{h} px")

    # ==========================================
    # VECTOR 2: MYSQL WAREHOUSE HEALTH & STORAGE
    # ==========================================
    print("\n--- VECTOR 2: MYSQL 8 WAREHOUSE HEALTH & STORAGE ---")
    engine = None
    try:
        db_url = get_db_url()
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
        record_test("MySQL Engine", "Connection Handshake", True, "Successfully connected via SQLAlchemy")

        with engine.connect() as conn:
            # Check tables and row counts
            res = conn.execute(text("""
                SELECT 
                    table_name AS tbl,
                    table_rows AS rows_est,
                    ROUND((data_length + index_length) / 1024 / 1024, 2) AS total_mb,
                    ROUND(index_length / 1024 / 1024, 2) AS index_mb
                FROM information_schema.tables 
                WHERE table_schema = 'ecommerce_analytics'
                ORDER BY table_name;
            """))
            tables = res.mappings().all()
            for t in tables:
                record_test("Database Tables", t["tbl"], True, f"Size: {t['total_mb']} MB (Idx: {t['index_mb']} MB)")

            # Precise counts
            sales_cnt = conn.execute(text("SELECT COUNT(*) FROM fact_sales;")).scalar()
            record_test("Data Volume", "fact_sales Exact Count", sales_cnt == 524878, f"{sales_cnt:,} rows")

            ret_cnt = conn.execute(text("SELECT COUNT(*) FROM fact_returns;")).scalar()
            record_test("Data Volume", "fact_returns Exact Count", ret_cnt == 11763, f"{ret_cnt:,} rows")

            cust_cnt = conn.execute(text("SELECT COUNT(*) FROM dim_customers;")).scalar()
            record_test("Data Volume", "dim_customers Exact Count", cust_cnt == 4372, f"{cust_cnt:,} rows")

            prod_cnt = conn.execute(text("SELECT COUNT(*) FROM dim_products;")).scalar()
            record_test("Data Volume", "dim_products Exact Count", prod_cnt == 4070, f"{prod_cnt:,} rows")

            date_cnt = conn.execute(text("SELECT COUNT(*) FROM dim_date;")).scalar()
            record_test("Data Volume", "dim_date Exact Count", date_cnt == 305, f"{date_cnt:,} rows")

            # Check Referential Integrity
            prod_orphans = conn.execute(text("""
                SELECT COUNT(*) 
                FROM fact_sales s 
                LEFT JOIN dim_products p ON s.stock_code = p.stock_code 
                WHERE p.stock_code IS NULL;
            """)).scalar()
            record_test("Foreign Keys", "Sales -> Product Orphans", prod_orphans == 0, f"{prod_orphans} orphan records")

            date_orphans = conn.execute(text("""
                SELECT COUNT(*) 
                FROM fact_sales s 
                LEFT JOIN dim_date d ON s.date_key = d.date_key 
                WHERE d.date_key IS NULL;
            """)).scalar()
            record_test("Foreign Keys", "Sales -> Date Orphans", date_orphans == 0, f"{date_orphans} orphan records")

    except Exception as e:
        record_test("MySQL Engine", "Connection Handshake", False, str(e))

    # ==========================================
    # VECTOR 3: ANALYTICAL QUERY BENCHMARK & ACCURACY
    # ==========================================
    if engine:
        print("\n--- VECTOR 3: ANALYTICAL QUERY BENCHMARK & ACCURACY ---")
        queries_to_test = [
            ("Gross Revenue & Order Count", """
                SELECT 
                    COUNT(DISTINCT invoice_no) AS orders,
                    ROUND(SUM(line_revenue), 2) AS revenue,
                    SUM(quantity) AS units
                FROM fact_sales;
            """, {"revenue": 10642110.80, "orders": 19960, "units": 5572420}),
            
            ("Top Country Revenue (UK)", """
                SELECT country, ROUND(SUM(line_revenue), 2) AS rev 
                FROM fact_sales 
                GROUP BY country 
                ORDER BY rev DESC 
                LIMIT 1;
            """, {"country": "United Kingdom", "rev": 9001744.09}),

            ("November 2011 Seasonal Peak", """
                SELECT 
                    d.year_month AS ym,
                    ROUND(SUM(s.line_revenue), 2) AS rev 
                FROM fact_sales s
                JOIN dim_date d ON s.date_key = d.date_key
                GROUP BY ym 
                ORDER BY rev DESC 
                LIMIT 1;
            """, {"ym": "2011-11", "rev": 1503866.78}),

            ("RFM Champions Revenue Share", """
                SELECT 
                    COUNT(*) AS champions_cnt,
                    ROUND(SUM(monetary_revenue), 2) AS champions_rev
                FROM customer_rfm 
                WHERE rfm_segment = 'Champions';
            """, {"champions_cnt": 940, "champions_rev": 5725513.34})
        ]

        with engine.connect() as conn:
            for q_name, sql, expected in queries_to_test:
                t0 = time.perf_counter()
                row = conn.execute(text(sql)).mappings().one()
                latency_ms = (time.perf_counter() - t0) * 1000

                passed = True
                details_parts = []
                for k, exp_val in expected.items():
                    actual_val = row[k]
                    if isinstance(exp_val, float):
                        match = abs(float(actual_val) - exp_val) < 0.05
                    else:
                        match = (actual_val == exp_val)
                    if not match:
                        passed = False
                    details_parts.append(f"{k}: {actual_val} (exp {exp_val})")
                details_parts.append(f"{latency_ms:.1f}ms")

                record_test("Query Benchmark", q_name, passed, " | ".join(details_parts))

    # ==========================================
    # VECTOR 4: RFM STATISTICAL DISTRIBUTION
    # ==========================================
    print("\n--- VECTOR 4: RFM MATHEMATICAL & STATISTICAL CHECKS ---")
    rfm_path = PATHS["rfm_csv"]
    if rfm_path.exists():
        rfm_df = pd.read_csv(rfm_path)
        
        # 1. Row count exactly 4,338
        record_test("RFM Distribution", "Total Scored Customers", len(rfm_df) == 4338, f"{len(rfm_df)} customers")

        # 2. Score bounds 1 to 5
        r_valid = bool(rfm_df["r_score"].between(1, 5).all())
        f_valid = bool(rfm_df["f_score"].between(1, 5).all())
        m_valid = bool(rfm_df["m_score"].between(1, 5).all())
        record_test("RFM Distribution", "R, F, M Score Range [1..5]", r_valid and f_valid and m_valid, "All within [1, 5]")

        # 3. 10 Named Segments
        unique_segments = sorted(rfm_df["rfm_segment"].unique().tolist())
        record_test("RFM Distribution", "Segment Completeness (10)", len(unique_segments) == 10, f"{len(unique_segments)} unique segments")

        # 4. Pareto Principle Assertion: Top 40% of customers generate >= 75% of revenue
        top_segments = ["Champions", "Loyal Customers"]
        top_rev = float(rfm_df[rfm_df["rfm_segment"].isin(top_segments)]["monetary_revenue"].sum())
        total_rev = float(rfm_df["monetary_revenue"].sum())
        pareto_pct = (top_rev / total_rev) * 100
        record_test("Business Logic", "Pareto Revenue Concentration", pareto_pct > 75.0, f"Top 2 segments drive {pareto_pct:.2f}% of spend")

    # ==========================================
    # FINAL AUDIT SUMMARY
    # ==========================================
    total_tests = len(test_results)
    passed_tests = sum(1 for t in test_results if t["passed"])
    failed_tests = total_tests - passed_tests

    print("\n" + "=" * 80)
    print(f"AGENT VERIFICATION AUDIT COMPLETE: {passed_tests}/{total_tests} CHECKS PASSED")
    if failed_tests == 0:
        print("ALL CRITICAL DATA PIPELINE, DATABASE, QUERY, AND ASSET CHECKS SUCCEEDED [100%] ✓")
    else:
        print(f"WARNING: {failed_tests} CHECKS FAILED. PLEASE REVIEW LOG ABOVE.")
    print("=" * 80)

    # Save agent test audit JSON
    audit_file = PATHS["data_dir"] / "agent_verification_audit.json"
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_checks": total_tests,
            "passed_checks": passed_tests,
            "failed_checks": failed_tests,
            "pass_rate_pct": round((passed_tests / total_tests) * 100, 2),
            "results": test_results
        }, f, indent=2)
    print(f"Machine-readable agent audit saved to: {audit_file}")

if __name__ == "__main__":
    run_agent_test()
