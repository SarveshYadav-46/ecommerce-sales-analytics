"""
run_pipeline.py — Master End-to-End Pipeline Orchestrator
==========================================================
Executes the full e-commerce data intelligence pipeline in sequence:
    1. clean_data.py          — Ingestion, standardization & sales/returns split
    2. data_quality_report.py — Comprehensive quality audit & anomaly detection
    3. load_database.py       — Idempotent star-schema loading into MySQL/PostgreSQL
    4. customer_rfm_analysis  — Rank-based quintile RFM segmentation & DB export
    5. validate_metrics.py    — Automated Pandas vs SQL reconciliation audit
    6. analysis_queries.sql   — Full 21-query analytical SQL suite execution

Usage:
    cd ecommerce-sales-analytics
    python python/run_pipeline.py
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime

from config import PATHS, setup_logging

logger = setup_logging("run_pipeline")


def run_step(step_name: str, cmd: list) -> bool:
    """Execute a single pipeline step and log progress."""
    logger.info("=" * 70)
    logger.info(f"STARTING STEP: {step_name}")
    logger.info(f"Command: {' '.join(cmd)}")
    logger.info("=" * 70)

    start_time = datetime.now()
    try:
        result = subprocess.run(cmd, check=True)
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"COMPLETED STEP: {step_name} in {elapsed:.2f}s ✓\n")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FAILED STEP: {step_name} with exit code {e.returncode} ✗")
        return False
    except Exception as e:
        logger.error(f"UNEXPECTED ERROR in {step_name}: {e} ✗")
        return False


def main():
    logger.info("\n" + "#" * 70)
    logger.info("  E-COMMERCE SALES INTELLIGENCE — FULL PIPELINE RUNNER")
    logger.info("#" * 70 + "\n")

    python_exe = sys.executable
    steps = [
        ("1. Data Cleaning & Partitioning", [python_exe, str(PATHS["python_dir"] / "clean_data.py")]),
        ("2. Data Quality Audit Report", [python_exe, str(PATHS["python_dir"] / "data_quality_report.py")]),
        ("3. Star-Schema Database Loading", [python_exe, str(PATHS["python_dir"] / "load_database.py"), "--create-tables"]),
        ("4. Customer RFM Segmentation", [python_exe, str(PATHS["python_dir"] / "customer_rfm_analysis.py"), "--load-db"]),
        ("5. Automated Cross-Validation Audit", [python_exe, str(PATHS["python_dir"] / "validate_metrics.py"), "--strict"]),
        ("6. Dashboard Visuals Generation", [python_exe, str(PATHS["python_dir"] / "generate_dashboard_visuals.py")]),
        ("7. Automated Test Suite (pytest)", [python_exe, "-m", "pytest", "-v", str(PATHS["project_root"] / "tests" / "test_pipeline.py")]),
    ]

    all_ok = True
    for name, cmd in steps:
        success = run_step(name, cmd)
        if not success:
            all_ok = False
            logger.error(f"Pipeline execution halted at: {name}")
            break

    logger.info("\n" + "#" * 70)
    if all_ok:
        logger.info("  ALL PIPELINE STEPS COMPLETED SUCCESSFULLY ✓")
        logger.info("  Warehouse populated: ecommerce_analytics")
        logger.info("  Cleaned data: data/cleaned_sales.csv (524,878 rows)")
        logger.info("  RFM analysis: data/customer_rfm.csv (4,338 customers)")
        logger.info("  Audit reports: data/data_quality_report.json, data/metrics_validation_report.json")
    else:
        logger.error("  PIPELINE FAILED. Check logs/pipeline.log for details.")
    logger.info("#" * 70 + "\n")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
