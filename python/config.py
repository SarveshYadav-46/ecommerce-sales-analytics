"""
config.py — Shared Configuration for E-Commerce Sales Analytics Pipeline
=========================================================================
Centralizes all paths, database connection logic, and logging setup.
Imported by every other Python module in this project.

Usage:
    from config import PATHS, get_db_url, setup_logging
"""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# ============================================================
# 1. PROJECT PATHS
# ============================================================

# Project root = parent of the python/ folder that contains this file
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# All canonical paths used across the pipeline
PATHS = {
    # --- Directories ---
    "project_root": PROJECT_ROOT,
    "data_dir": PROJECT_ROOT / "data",
    "python_dir": PROJECT_ROOT / "python",
    "sql_dir": PROJECT_ROOT / "sql",
    "tableau_dir": PROJECT_ROOT / "tableau",
    "report_dir": PROJECT_ROOT / "report",
    "screenshots_dir": PROJECT_ROOT / "screenshots",
    "logs_dir": PROJECT_ROOT / "logs",

    # --- Input ---
    "raw_excel": PROJECT_ROOT / "data" / "Online Retail.xlsx",

    # --- Cleaned outputs ---
    "cleaned_sales_csv": PROJECT_ROOT / "data" / "cleaned_sales.csv",
    "returns_csv": PROJECT_ROOT / "data" / "returns_analysis.csv",
    "quality_report_json": PROJECT_ROOT / "data" / "data_quality_report.json",

    # --- RFM output ---
    "rfm_csv": PROJECT_ROOT / "data" / "customer_rfm.csv",

    # --- SQL scripts ---
    "create_database_sql": PROJECT_ROOT / "sql" / "create_database.sql",
    "create_tables_sql": PROJECT_ROOT / "sql" / "create_tables.sql",
    "analysis_queries_sql": PROJECT_ROOT / "sql" / "analysis_queries.sql",

    # --- Tableau ---
    "dashboard_guide": PROJECT_ROOT / "tableau" / "dashboard_build_guide.md",

    # --- Reports ---
    "project_report": PROJECT_ROOT / "report" / "project_report.md",
    "readme": PROJECT_ROOT / "README.md",
}

# Cleaned-sales column order (used for export consistency)
CLEANED_COLUMNS = [
    "invoice_no", "stock_code", "description", "quantity",
    "invoice_date", "unit_price", "customer_id", "country",
    "line_revenue", "year", "month", "quarter", "year_month",
]

# Returns-CSV column order
RETURNS_COLUMNS = [
    "invoice_no", "stock_code", "description", "quantity",
    "invoice_date", "unit_price", "customer_id", "country",
    "line_revenue", "year", "month", "quarter", "year_month",
    "return_flag",
]


# ============================================================
# 2. DATABASE CONFIGURATION
# ============================================================

def _load_env() -> None:
    """Load .env from the project root if it exists."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        # Try parent directories as a fallback
        load_dotenv()


def get_db_url(include_db: bool = True) -> str:
    """
    Build a SQLAlchemy database URL from environment variables.

    Parameters
    ----------
    include_db : bool
        If True, append the database name to the URL.
        Set to False when creating the database itself.

    Returns
    -------
    str
        A SQLAlchemy-compatible connection string.

    Raises
    ------
    EnvironmentError
        If required environment variables are missing.

    Environment Variables
    ---------------------
    DB_ENGINE   : 'mysql' or 'postgresql' (default: 'mysql')
    DB_HOST     : Database host (default: 'localhost')
    DB_PORT     : Database port (default: engine-specific)
    DB_USER     : Database user (required)
    DB_PASSWORD : Database password (required)
    DB_NAME     : Database name (default: 'ecommerce_analytics')
    """
    _load_env()

    engine = os.getenv("DB_ENGINE", "mysql").lower().strip()
    host = os.getenv("DB_HOST", "localhost")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME", "ecommerce_analytics")

    # Validate required credentials
    if not user or not password:
        raise EnvironmentError(
            "DB_USER and DB_PASSWORD must be set in the .env file. "
            "Copy .env.example to .env and fill in your credentials."
        )

    # Engine-specific defaults and driver strings
    if engine == "mysql":
        port = os.getenv("DB_PORT", "3306")
        driver = "mysql+pymysql"
    elif engine in ("postgresql", "postgres"):
        port = os.getenv("DB_PORT", "5432")
        driver = "postgresql+psycopg2"
    else:
        raise ValueError(
            f"Unsupported DB_ENGINE='{engine}'. Use 'mysql' or 'postgresql'."
        )

    # Build URL
    base_url = f"{driver}://{user}:{password}@{host}:{port}"
    if include_db:
        return f"{base_url}/{db_name}"
    return base_url


def get_db_name() -> str:
    """Return the database name from the environment (default: ecommerce_analytics)."""
    _load_env()
    return os.getenv("DB_NAME", "ecommerce_analytics")


# ============================================================
# 3. LOGGING SETUP
# ============================================================

def setup_logging(
    name: str = "ecommerce_analytics",
    level: int = logging.INFO,
    log_to_file: bool = True,
) -> logging.Logger:
    """
    Configure and return a logger with console and optional file output.

    Parameters
    ----------
    name : str
        Logger name (appears in log records).
    level : int
        Logging level (default: logging.INFO).
    log_to_file : bool
        If True, also write logs to logs/pipeline.log.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Formatter
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(name)-24s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler with UTF-8 support
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # File handler
    if log_to_file:
        log_dir = PATHS["logs_dir"]
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / "pipeline.log", encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    return logger


# ============================================================
# 4. QUICK SELF-TEST
# ============================================================

if __name__ == "__main__":
    # Verify paths resolve correctly
    log = setup_logging("config_test")
    log.info("Config self-test started")
    log.info(f"Project root : {PROJECT_ROOT}")
    log.info(f"Raw Excel    : {PATHS['raw_excel']}")
    log.info(f"Excel exists : {PATHS['raw_excel'].exists()}")

    # Test DB URL construction (will fail gracefully if .env is missing)
    try:
        url = get_db_url()
        # Mask the password in output
        masked = url.split("@")
        if len(masked) == 2:
            log.info(f"DB URL       : ***@{masked[1]}")
        else:
            log.info("DB URL       : (constructed successfully)")
    except EnvironmentError as e:
        log.warning(f"DB URL       : {e}")

    log.info("Config self-test complete ✓")
