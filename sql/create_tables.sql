-- ============================================================
-- create_tables.sql
-- Star Schema DDL for ecommerce_analytics
-- ============================================================
-- Tables: dim_date, dim_products, dim_customers,
--         fact_sales, fact_returns
--
-- MySQL:
--   mysql -u root -p ecommerce_analytics < sql/create_tables.sql
--
-- PostgreSQL:
--   psql -U postgres -d ecommerce_analytics -f sql/create_tables.sql
--
-- Design notes:
--   • Dimensions are created first (referenced by facts).
--   • fact_sales.customer_id is NULLABLE (anonymous transactions).
--   • country is stored in BOTH fact tables AND dim_customers.
--     Rationale: anonymous transactions (customer_id IS NULL) still
--     have a known country. Storing country only in dim_customers
--     would lose this information for ~25% of transactions.
--     This is standard Kimball-style pragmatic denormalization.
--   • Joins must not duplicate revenue: use fact tables directly
--     for revenue aggregation; join dims only for attributes.
-- ============================================================


-- ==================== MySQL Version ====================
-- (For PostgreSQL, see the section at the bottom)

USE ecommerce_analytics;


-- --------------------------------------------------------
-- DIMENSION: dim_date
-- --------------------------------------------------------
-- date_key uses YYYYMMDD integer format (e.g., 20101201).
-- Granularity: one row per calendar date.
-- --------------------------------------------------------

CREATE TABLE IF NOT EXISTS dim_date (
    `date_key`     INT          NOT NULL  COMMENT 'YYYYMMDD integer key',
    `full_date`    DATE         NOT NULL  COMMENT 'Calendar date',
    `year`         SMALLINT     NOT NULL,
    `month`        SMALLINT     NOT NULL  COMMENT '1-12',
    `quarter`      SMALLINT     NOT NULL  COMMENT '1-4',
    `year_month`   VARCHAR(7)   NOT NULL  COMMENT 'YYYY-MM format',
    `day_of_week`  SMALLINT     NOT NULL  COMMENT '0=Monday … 6=Sunday',
    `day_name`     VARCHAR(9)   NOT NULL  COMMENT 'Monday, Tuesday, …',

    PRIMARY KEY (`date_key`),
    INDEX idx_date_year_month (`year_month`),
    INDEX idx_date_year       (`year`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Date dimension — one row per calendar date';


-- --------------------------------------------------------
-- DIMENSION: dim_products
-- --------------------------------------------------------
-- Granularity: one row per unique stock_code.
-- Description is the most common non-null description
-- across all transactions for that stock_code.
-- --------------------------------------------------------

CREATE TABLE IF NOT EXISTS dim_products (
    stock_code   VARCHAR(20)  CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    description  VARCHAR(255) NULL      COMMENT 'Most common product description',

    PRIMARY KEY (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Product dimension — one row per stock code';


-- --------------------------------------------------------
-- DIMENSION: dim_customers
-- --------------------------------------------------------
-- Granularity: one row per unique customer_id.
-- Only identified customers (non-NULL customer_id).
-- Country is the most frequently associated country.
-- --------------------------------------------------------

CREATE TABLE IF NOT EXISTS dim_customers (
    customer_id  INT          NOT NULL,
    country      VARCHAR(50)  NULL      COMMENT 'Most frequent country for this customer',

    PRIMARY KEY (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Customer dimension — identified customers only';


-- --------------------------------------------------------
-- FACT: fact_sales
-- --------------------------------------------------------
-- Granularity: one row per invoice line item (eligible sale).
-- Eligible sale: NOT C-invoice AND quantity > 0 AND unit_price > 0.
-- Revenue = quantity × unit_price (gross sales).
-- customer_id is NULLABLE (anonymous sales count in revenue
-- and orders but not in customer-level KPIs).
-- --------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_sales (
    sale_id      BIGINT       NOT NULL AUTO_INCREMENT,
    invoice_no   VARCHAR(20)  NOT NULL,
    stock_code   VARCHAR(20)  CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    customer_id  INT          NULL     COMMENT 'NULL = anonymous customer',
    date_key     INT          NOT NULL,
    quantity     INT          NOT NULL COMMENT 'Always > 0 for eligible sales',
    unit_price   DECIMAL(10,2) NOT NULL COMMENT 'Always > 0 for eligible sales',
    line_revenue DECIMAL(12,2) NOT NULL COMMENT 'quantity × unit_price',
    country      VARCHAR(50)  NULL     COMMENT 'Transaction country (denormalized)',

    PRIMARY KEY (sale_id),

    CONSTRAINT fk_sales_product
        FOREIGN KEY (stock_code) REFERENCES dim_products(stock_code)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_sales_customer
        FOREIGN KEY (customer_id) REFERENCES dim_customers(customer_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_sales_date
        FOREIGN KEY (date_key) REFERENCES dim_date(date_key)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    INDEX idx_sales_invoice  (invoice_no),
    INDEX idx_sales_date     (date_key),
    INDEX idx_sales_customer (customer_id),
    INDEX idx_sales_stock    (stock_code),
    INDEX idx_sales_country  (country)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Fact table — eligible sale line items';


-- --------------------------------------------------------
-- FACT: fact_returns
-- --------------------------------------------------------
-- Contains: C-invoices, negative-quantity rows, adjustments
-- (non-positive price), zero-quantity anomalies, and any
-- invalid-numeric rows.
-- return_flag documents the classification reason.
-- --------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_returns (
    return_id    BIGINT       NOT NULL AUTO_INCREMENT,
    invoice_no   VARCHAR(20)  NOT NULL,
    stock_code   VARCHAR(20)  CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    customer_id  INT          NULL,
    date_key     INT          NOT NULL,
    quantity     INT          NOT NULL COMMENT 'May be negative for returns',
    unit_price   DECIMAL(10,2) NOT NULL COMMENT 'May be zero or negative',
    line_revenue DECIMAL(12,2) NOT NULL COMMENT 'quantity × unit_price',
    return_flag  VARCHAR(50)  NOT NULL COMMENT 'Classification flag',
    country      VARCHAR(50)  NULL     COMMENT 'Transaction country (denormalized)',

    PRIMARY KEY (return_id),

    CONSTRAINT fk_returns_product
        FOREIGN KEY (stock_code) REFERENCES dim_products(stock_code)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_returns_customer
        FOREIGN KEY (customer_id) REFERENCES dim_customers(customer_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    CONSTRAINT fk_returns_date
        FOREIGN KEY (date_key) REFERENCES dim_date(date_key)
        ON UPDATE CASCADE ON DELETE RESTRICT,

    INDEX idx_returns_invoice  (invoice_no),
    INDEX idx_returns_date     (date_key),
    INDEX idx_returns_customer (customer_id),
    INDEX idx_returns_flag     (return_flag),
    INDEX idx_returns_country  (country)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Fact table — returns, cancellations, and adjustments';


-- ============================================================
-- VERIFICATION QUERIES (run after data load)
-- ============================================================

-- SELECT 'dim_date'      AS tbl, COUNT(*) AS rows FROM dim_date
-- UNION ALL
-- SELECT 'dim_products',         COUNT(*)         FROM dim_products
-- UNION ALL
-- SELECT 'dim_customers',        COUNT(*)         FROM dim_customers
-- UNION ALL
-- SELECT 'fact_sales',           COUNT(*)         FROM fact_sales
-- UNION ALL
-- SELECT 'fact_returns',         COUNT(*)         FROM fact_returns;

-- Revenue sanity check (should match cleaned_sales.csv total):
-- SELECT ROUND(SUM(line_revenue), 2) AS total_revenue FROM fact_sales;


-- ============================================================
-- PostgreSQL Version (uncomment if using PostgreSQL)
-- ============================================================
-- Key differences:
--   • BIGSERIAL instead of BIGINT AUTO_INCREMENT
--   • No ENGINE or CHARSET clauses
--   • No COMMENT on columns (use COMMENT ON ... IS '...' separately)
--   • INDEX must be created separately with CREATE INDEX
--
-- Example:
--
-- CREATE TABLE IF NOT EXISTS dim_date (
--     date_key     INT          NOT NULL,
--     full_date    DATE         NOT NULL,
--     year         SMALLINT     NOT NULL,
--     month        SMALLINT     NOT NULL,
--     quarter      SMALLINT     NOT NULL,
--     year_month   VARCHAR(7)   NOT NULL,
--     day_of_week  SMALLINT     NOT NULL,
--     day_name     VARCHAR(9)   NOT NULL,
--     PRIMARY KEY (date_key)
-- );
-- CREATE INDEX IF NOT EXISTS idx_date_year_month ON dim_date(year_month);
-- CREATE INDEX IF NOT EXISTS idx_date_year ON dim_date(year);
--
-- CREATE TABLE IF NOT EXISTS fact_sales (
--     sale_id      BIGSERIAL    PRIMARY KEY,
--     invoice_no   VARCHAR(20)  NOT NULL,
--     stock_code   VARCHAR(20)  NOT NULL REFERENCES dim_products(stock_code),
--     customer_id  INT          NULL     REFERENCES dim_customers(customer_id),
--     date_key     INT          NOT NULL REFERENCES dim_date(date_key),
--     quantity     INT          NOT NULL,
--     unit_price   DECIMAL(10,2) NOT NULL,
--     line_revenue DECIMAL(12,2) NOT NULL,
--     country      VARCHAR(50)  NULL
-- );
-- CREATE INDEX IF NOT EXISTS idx_sales_invoice ON fact_sales(invoice_no);
-- CREATE INDEX IF NOT EXISTS idx_sales_date ON fact_sales(date_key);
-- CREATE INDEX IF NOT EXISTS idx_sales_customer ON fact_sales(customer_id);
-- CREATE INDEX IF NOT EXISTS idx_sales_stock ON fact_sales(stock_code);
-- CREATE INDEX IF NOT EXISTS idx_sales_country ON fact_sales(country);
