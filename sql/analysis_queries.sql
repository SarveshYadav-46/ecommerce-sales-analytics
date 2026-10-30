-- ============================================================
-- analysis_queries.sql
-- Analytical Queries for E-Commerce Sales Intelligence
-- ============================================================
-- Database : ecommerce_analytics
-- Engine   : MySQL 8+ (PostgreSQL notes included where syntax differs)
-- Source   : fact_sales, fact_returns, dim_products, dim_customers, dim_date
--
-- Conventions:
--   • Revenue   = SUM(line_revenue) from fact_sales ONLY (gross sales).
--   • Orders    = COUNT(DISTINCT invoice_no) from fact_sales.
--   • Customers = COUNT(DISTINCT customer_id) WHERE customer_id IS NOT NULL.
--   • Anonymous sales (customer_id IS NULL) count in revenue and orders
--     but are EXCLUDED from customer-level KPIs.
--   • Cancellation/return data lives in fact_returns — never mixed
--     with fact_sales, so joins cannot duplicate revenue.
-- ============================================================

USE ecommerce_analytics;


-- ============================================================
-- Q1: TOTAL REVENUE (Gross Sales)
-- ============================================================
-- Formula : SUM(quantity × unit_price) across all eligible sales.
--           Equivalent to SUM(line_revenue) since line_revenue = qty × price.
-- Business: Top-line revenue figure for executive reporting.
-- Edge case: Includes anonymous customers. Does NOT subtract returns.
--            Call this "Gross Sales Revenue" — not net revenue.

SELECT
    ROUND(SUM(line_revenue), 2)    AS total_revenue,
    FORMAT(SUM(line_revenue), 2)   AS total_revenue_formatted
FROM fact_sales;


-- ============================================================
-- Q2: DISTINCT INVOICES (Total Orders)
-- ============================================================
-- Formula : COUNT(DISTINCT invoice_no) from fact_sales.
-- Business: Order volume — distinct transactions, not line items.
-- Edge case: One invoice can have many line items (products).
--            Anonymous orders are included.

SELECT
    COUNT(DISTINCT invoice_no) AS total_orders
FROM fact_sales;


-- ============================================================
-- Q3: UNIQUE CUSTOMERS
-- ============================================================
-- Formula : COUNT(DISTINCT customer_id) WHERE customer_id IS NOT NULL.
-- Business: Size of the identified customer base.
-- Edge case: Denominator explicitly excludes NULL customer_id.
--            Anonymous rows exist but are uncountable as individuals.

SELECT
    COUNT(DISTINCT customer_id)    AS unique_customers,
    COUNT(*)                       AS total_line_items,
    SUM(CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END) AS anonymous_line_items,
    ROUND(
        SUM(CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END) / COUNT(*) * 100, 2
    ) AS anonymous_pct
FROM fact_sales;


-- ============================================================
-- Q4: UNITS SOLD
-- ============================================================
-- Formula : SUM(quantity) from fact_sales.
-- Business: Total product units moved — measures physical volume.
-- Edge case: All quantities in fact_sales are > 0 (by cleaning rules).

SELECT
    SUM(quantity)          AS total_units_sold,
    FORMAT(SUM(quantity), 0) AS units_formatted
FROM fact_sales;


-- ============================================================
-- Q5: MONTHLY REVENUE TREND
-- ============================================================
-- Formula : SUM(line_revenue) grouped by year_month from dim_date.
-- Business: Time-series trend for spotting seasonality, growth, dips.
-- Edge case: Partial months at start/end of dataset may under-report.
--            Dec 2011 data typically ends on 2011-12-09.
-- SQL features: JOIN, GROUP BY, ORDER BY

SELECT
    d.year_month,
    d.year,
    d.month,
    COUNT(DISTINCT s.invoice_no)   AS orders,
    SUM(s.quantity)                 AS units_sold,
    ROUND(SUM(s.line_revenue), 2)  AS monthly_revenue
FROM fact_sales s
JOIN dim_date d ON s.date_key = d.date_key
GROUP BY d.year_month, d.year, d.month
ORDER BY d.year_month;


-- ============================================================
-- Q6: YEARLY & QUARTERLY PERFORMANCE
-- ============================================================
-- Formula : Revenue and orders aggregated by year and quarter.
-- Business: High-level performance comparison across periods.
-- Edge case: 2010 has only Dec data; 2011-Q4 is partial (ends ~Dec 9).
-- SQL features: GROUP BY with ROLLUP for subtotals

-- 6A: By Year
SELECT
    d.year,
    COUNT(DISTINCT s.invoice_no)   AS orders,
    COUNT(DISTINCT s.customer_id)  AS customers,
    SUM(s.quantity)                 AS units_sold,
    ROUND(SUM(s.line_revenue), 2)  AS revenue
FROM fact_sales s
JOIN dim_date d ON s.date_key = d.date_key
GROUP BY d.year
ORDER BY d.year;

-- 6B: By Year-Quarter
SELECT
    d.year,
    d.quarter,
    CONCAT(d.year, '-Q', d.quarter) AS year_quarter,
    COUNT(DISTINCT s.invoice_no)     AS orders,
    ROUND(SUM(s.line_revenue), 2)    AS revenue,
    ROUND(SUM(s.line_revenue) / COUNT(DISTINCT s.invoice_no), 2) AS aov
FROM fact_sales s
JOIN dim_date d ON s.date_key = d.date_key
GROUP BY d.year, d.quarter
ORDER BY d.year, d.quarter;


-- ============================================================
-- Q7: TOP 10 PRODUCTS BY REVENUE
-- ============================================================
-- Formula : SUM(line_revenue) per stock_code, ranked descending.
-- Business: Identifies revenue drivers — focus marketing and inventory.
-- Edge case: Products with NULL description still counted by stock_code.
-- SQL features: JOIN, GROUP BY, ORDER BY, LIMIT, window function for rank

SELECT
    p.stock_code,
    p.description,
    ROUND(SUM(s.line_revenue), 2)   AS product_revenue,
    SUM(s.quantity)                   AS units_sold,
    COUNT(DISTINCT s.invoice_no)     AS order_count,
    ROUND(SUM(s.line_revenue) / SUM(s.quantity), 2) AS avg_unit_price,
    RANK() OVER (ORDER BY SUM(s.line_revenue) DESC) AS revenue_rank
FROM fact_sales s
JOIN dim_products p ON s.stock_code = p.stock_code
GROUP BY p.stock_code, p.description
ORDER BY product_revenue DESC
LIMIT 10;


-- ============================================================
-- Q8: TOP 10 PRODUCTS BY QUANTITY
-- ============================================================
-- Formula : SUM(quantity) per stock_code, ranked descending.
-- Business: Most popular items by volume — supply chain and restocking.
-- Edge case: High volume ≠ high revenue (e.g., cheap items).

SELECT
    p.stock_code,
    p.description,
    SUM(s.quantity)                   AS total_quantity,
    ROUND(SUM(s.line_revenue), 2)    AS total_revenue,
    COUNT(DISTINCT s.invoice_no)     AS order_count,
    RANK() OVER (ORDER BY SUM(s.quantity) DESC) AS quantity_rank
FROM fact_sales s
JOIN dim_products p ON s.stock_code = p.stock_code
GROUP BY p.stock_code, p.description
ORDER BY total_quantity DESC
LIMIT 10;


-- ============================================================
-- Q9: BOTTOM PRODUCTS (Minimum Volume Filter)
-- ============================================================
-- Formula : Products with lowest revenue, filtered to those with
--           at least 10 orders (avoids one-off outliers).
-- Business: Candidates for discontinuation or promotion.
-- Edge case: Without the minimum filter, single-sale items dominate
--            the bottom list and are not actionable.
-- SQL features: CTE, HAVING, ORDER BY ASC

WITH product_performance AS (
    SELECT
        p.stock_code,
        p.description,
        SUM(s.quantity)                 AS total_quantity,
        ROUND(SUM(s.line_revenue), 2)  AS total_revenue,
        COUNT(DISTINCT s.invoice_no)   AS order_count
    FROM fact_sales s
    JOIN dim_products p ON s.stock_code = p.stock_code
    GROUP BY p.stock_code, p.description
    HAVING COUNT(DISTINCT s.invoice_no) >= 10
)
SELECT *
FROM product_performance
ORDER BY total_revenue ASC
LIMIT 10;


-- ============================================================
-- Q10: COUNTRY — REVENUE AND ORDERS
-- ============================================================
-- Formula : Revenue and orders grouped by country.
-- Business: Geographic performance — where to expand or invest.
-- Edge case: country is denormalized in fact_sales, so even anonymous
--            customers contribute their country. No data loss from NULLs.
-- SQL features: GROUP BY, window function for % contribution

SELECT
    s.country,
    COUNT(DISTINCT s.invoice_no)     AS orders,
    COUNT(DISTINCT s.customer_id)    AS customers,
    SUM(s.quantity)                   AS units_sold,
    ROUND(SUM(s.line_revenue), 2)    AS revenue,
    ROUND(
        SUM(s.line_revenue) / SUM(SUM(s.line_revenue)) OVER () * 100, 2
    ) AS revenue_pct
FROM fact_sales s
GROUP BY s.country
ORDER BY revenue DESC;


-- ============================================================
-- Q11: AVERAGE ORDER VALUE (AOV)
-- ============================================================
-- Formula : Total Revenue / COUNT(DISTINCT invoice_no).
-- Business: Basket size metric — tracks upselling effectiveness.
-- Edge case: AOV includes anonymous orders. One invoice = one order,
--            regardless of how many line items it contains.
-- SQL features: Subquery for invoice-level aggregation

-- 11A: Overall AOV
SELECT
    ROUND(SUM(line_revenue) / COUNT(DISTINCT invoice_no), 2) AS overall_aov
FROM fact_sales;

-- 11B: Monthly AOV trend
SELECT
    d.year_month,
    COUNT(DISTINCT s.invoice_no)    AS orders,
    ROUND(SUM(s.line_revenue), 2)   AS revenue,
    ROUND(SUM(s.line_revenue) / COUNT(DISTINCT s.invoice_no), 2) AS monthly_aov
FROM fact_sales s
JOIN dim_date d ON s.date_key = d.date_key
GROUP BY d.year_month
ORDER BY d.year_month;


-- ============================================================
-- Q12: NEW VS REPEAT CUSTOMERS (by month)
-- ============================================================
-- Formula :
--   • New     = customer whose first-ever purchase is in this month.
--   • Repeat  = customer who purchased before this month.
-- Business: Acquisition vs retention balance. Healthy business needs both.
-- Edge case: Anonymous customers (NULL customer_id) are excluded entirely.
--            Denominator = identified customers who purchased in that month.
-- SQL features: CTE, MIN() for first purchase, CASE WHEN, window function

WITH customer_first_purchase AS (
    -- Find each customer's first purchase month
    SELECT
        s.customer_id,
        MIN(d.year_month) AS first_purchase_month
    FROM fact_sales s
    JOIN dim_date d ON s.date_key = d.date_key
    WHERE s.customer_id IS NOT NULL
    GROUP BY s.customer_id
),
monthly_customers AS (
    -- List distinct customers per month
    SELECT DISTINCT
        d.year_month,
        s.customer_id
    FROM fact_sales s
    JOIN dim_date d ON s.date_key = d.date_key
    WHERE s.customer_id IS NOT NULL
)
SELECT
    mc.year_month,
    COUNT(*)                                                        AS total_customers,
    SUM(CASE WHEN mc.year_month = cfp.first_purchase_month
             THEN 1 ELSE 0 END)                                     AS new_customers,
    SUM(CASE WHEN mc.year_month > cfp.first_purchase_month
             THEN 1 ELSE 0 END)                                     AS repeat_customers,
    ROUND(
        SUM(CASE WHEN mc.year_month > cfp.first_purchase_month THEN 1 ELSE 0 END)
        / COUNT(*) * 100, 2
    )                                                                AS repeat_pct
FROM monthly_customers mc
JOIN customer_first_purchase cfp ON mc.customer_id = cfp.customer_id
GROUP BY mc.year_month
ORDER BY mc.year_month;


-- ============================================================
-- Q13: OVERALL REPEAT RATE
-- ============================================================
-- Formula : (Customers with > 1 distinct invoice) / Total Customers × 100.
-- Business: Customer loyalty indicator. Higher = stickier base.
-- Edge case: Denominator = identified customers only (non-NULL customer_id).
-- SQL features: CTE, CASE, COUNT with condition

WITH customer_orders AS (
    SELECT
        customer_id,
        COUNT(DISTINCT invoice_no) AS order_count
    FROM fact_sales
    WHERE customer_id IS NOT NULL
    GROUP BY customer_id
)
SELECT
    COUNT(*)                                                    AS total_customers,
    SUM(CASE WHEN order_count > 1 THEN 1 ELSE 0 END)          AS repeat_customers,
    SUM(CASE WHEN order_count = 1 THEN 1 ELSE 0 END)          AS one_time_customers,
    ROUND(
        SUM(CASE WHEN order_count > 1 THEN 1 ELSE 0 END)
        / COUNT(*) * 100, 2
    )                                                           AS repeat_rate_pct,
    ROUND(AVG(order_count), 2)                                  AS avg_orders_per_customer,
    MAX(order_count)                                            AS max_orders
FROM customer_orders;


-- ============================================================
-- Q14: PURCHASE FREQUENCY DISTRIBUTION
-- ============================================================
-- Formula : Group customers by their number of orders; count each bucket.
-- Business: Understand the frequency spectrum — how many buy once vs many.
-- Edge case: Excludes anonymous customers.
-- SQL features: CTE, CASE for bucketing

WITH customer_freq AS (
    SELECT
        customer_id,
        COUNT(DISTINCT invoice_no) AS order_count
    FROM fact_sales
    WHERE customer_id IS NOT NULL
    GROUP BY customer_id
)
SELECT
    CASE
        WHEN order_count = 1    THEN '1 order'
        WHEN order_count = 2    THEN '2 orders'
        WHEN order_count = 3    THEN '3 orders'
        WHEN order_count BETWEEN 4 AND 5   THEN '4-5 orders'
        WHEN order_count BETWEEN 6 AND 10  THEN '6-10 orders'
        WHEN order_count BETWEEN 11 AND 20 THEN '11-20 orders'
        ELSE '21+ orders'
    END AS frequency_bucket,
    COUNT(*)                AS customer_count,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER () * 100, 2) AS pct_of_customers,
    MIN(order_count) AS bucket_min,
    MAX(order_count) AS bucket_max
FROM customer_freq
GROUP BY
    CASE
        WHEN order_count = 1    THEN '1 order'
        WHEN order_count = 2    THEN '2 orders'
        WHEN order_count = 3    THEN '3 orders'
        WHEN order_count BETWEEN 4 AND 5   THEN '4-5 orders'
        WHEN order_count BETWEEN 6 AND 10  THEN '6-10 orders'
        WHEN order_count BETWEEN 11 AND 20 THEN '11-20 orders'
        ELSE '21+ orders'
    END,
    CASE
        WHEN order_count = 1    THEN 1
        WHEN order_count = 2    THEN 2
        WHEN order_count = 3    THEN 3
        WHEN order_count BETWEEN 4 AND 5   THEN 4
        WHEN order_count BETWEEN 6 AND 10  THEN 5
        WHEN order_count BETWEEN 11 AND 20 THEN 6
        ELSE 7
    END
ORDER BY
    CASE
        WHEN order_count = 1    THEN 1
        WHEN order_count = 2    THEN 2
        WHEN order_count = 3    THEN 3
        WHEN order_count BETWEEN 4 AND 5   THEN 4
        WHEN order_count BETWEEN 6 AND 10  THEN 5
        WHEN order_count BETWEEN 11 AND 20 THEN 6
        ELSE 7
    END;


-- ============================================================
-- Q15: RFM ANALYSIS (SQL-Based)
-- ============================================================
-- Formula :
--   R = days since last purchase (lower = better, higher score)
--   F = count of distinct invoices (higher = better, higher score)
--   M = total revenue (higher = better, higher score)
--   Scores: NTILE(5) — 5 = best, 1 = worst.
-- Business: Segment customers for targeted marketing.
-- Edge case: Reference date = MAX(invoice_date) + 1 day in the dataset.
--            Excludes anonymous customers.
-- SQL features: CTE, NTILE window function, CASE for segmentation
-- Note: These segments are analytical heuristics, not verified
--       behavioral classes. They depend on score thresholds.

WITH rfm_base AS (
    SELECT
        s.customer_id,
        DATEDIFF(
            (SELECT DATE_ADD(MAX(d2.full_date), INTERVAL 1 DAY) FROM dim_date d2),
            MAX(d.full_date)
        ) AS recency_days,
        COUNT(DISTINCT s.invoice_no) AS frequency,
        ROUND(SUM(s.line_revenue), 2) AS monetary
    FROM fact_sales s
    JOIN dim_date d ON s.date_key = d.date_key
    WHERE s.customer_id IS NOT NULL
    GROUP BY s.customer_id
),
rfm_scored AS (
    SELECT
        customer_id,
        recency_days,
        frequency,
        monetary,
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,  -- lower recency = higher score
        NTILE(5) OVER (ORDER BY frequency ASC)      AS f_score,  -- higher frequency = higher score
        NTILE(5) OVER (ORDER BY monetary ASC)        AS m_score   -- higher monetary = higher score
    FROM rfm_base
)
SELECT
    customer_id,
    recency_days,
    frequency,
    monetary,
    r_score,
    f_score,
    m_score,
    CONCAT(r_score, f_score, m_score) AS rfm_combined,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4
            THEN 'Champions'
        WHEN r_score >= 3 AND f_score >= 3 AND m_score >= 3
            THEN 'Loyal Customers'
        WHEN r_score >= 3 AND f_score >= 1 AND m_score >= 1
            AND (f_score < 3 OR m_score < 3)
            THEN 'Potential Loyalists'
        WHEN r_score >= 4 AND f_score <= 2
            THEN 'New Customers'
        WHEN r_score <= 2 AND f_score >= 3 AND m_score >= 3
            THEN 'At Risk'
        WHEN r_score <= 2 AND f_score >= 4 AND m_score >= 4
            THEN 'Cant Lose Them'
        WHEN r_score <= 2 AND f_score <= 2
            THEN 'Lost'
        ELSE 'Need Attention'
    END AS rfm_segment
FROM rfm_scored
ORDER BY monetary DESC;

-- PostgreSQL alternative for DATEDIFF:
--   (SELECT MAX(d2.full_date) + INTERVAL '1 day' FROM dim_date d2)::date
--   - MAX(d.full_date) AS recency_days


-- ============================================================
-- Q15B: RFM SEGMENT SUMMARY
-- ============================================================
-- Aggregate the RFM segments to see segment sizes and values.

WITH rfm_base AS (
    SELECT
        s.customer_id,
        DATEDIFF(
            (SELECT DATE_ADD(MAX(d2.full_date), INTERVAL 1 DAY) FROM dim_date d2),
            MAX(d.full_date)
        ) AS recency_days,
        COUNT(DISTINCT s.invoice_no) AS frequency,
        ROUND(SUM(s.line_revenue), 2) AS monetary
    FROM fact_sales s
    JOIN dim_date d ON s.date_key = d.date_key
    WHERE s.customer_id IS NOT NULL
    GROUP BY s.customer_id
),
rfm_scored AS (
    SELECT
        customer_id, recency_days, frequency, monetary,
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,
        NTILE(5) OVER (ORDER BY frequency ASC)      AS f_score,
        NTILE(5) OVER (ORDER BY monetary ASC)        AS m_score
    FROM rfm_base
),
rfm_segmented AS (
    SELECT *,
        CASE
            WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Champions'
            WHEN r_score >= 3 AND f_score >= 3 AND m_score >= 3 THEN 'Loyal Customers'
            WHEN r_score >= 3 AND f_score >= 1 AND m_score >= 1
                AND (f_score < 3 OR m_score < 3) THEN 'Potential Loyalists'
            WHEN r_score >= 4 AND f_score <= 2 THEN 'New Customers'
            WHEN r_score <= 2 AND f_score >= 3 AND m_score >= 3 THEN 'At Risk'
            WHEN r_score <= 2 AND f_score >= 4 AND m_score >= 4 THEN 'Cant Lose Them'
            WHEN r_score <= 2 AND f_score <= 2 THEN 'Lost'
            ELSE 'Need Attention'
        END AS rfm_segment
    FROM rfm_scored
)
SELECT
    rfm_segment,
    COUNT(*)                           AS customer_count,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER () * 100, 2) AS pct_of_customers,
    ROUND(AVG(recency_days), 0)        AS avg_recency,
    ROUND(AVG(frequency), 1)           AS avg_frequency,
    ROUND(AVG(monetary), 2)            AS avg_monetary,
    ROUND(SUM(monetary), 2)            AS total_monetary
FROM rfm_segmented
GROUP BY rfm_segment
ORDER BY total_monetary DESC;


-- ============================================================
-- Q16: CANCELLATION / RETURN ANALYSIS
-- ============================================================
-- Formula : Analyze fact_returns by return_flag category.
-- Business: Understand the volume and value of non-sale transactions.
-- Edge case: return_flag values: C_invoice, negative_quantity,
--            C_invoice|negative_quantity, adjustment_non_positive_price,
--            zero_quantity, invalid_numeric.
--            These are PROXIES — not verified refund/return records.
-- SQL features: GROUP BY, CASE

-- 16A: Overall return/cancellation summary
SELECT
    COUNT(*)                           AS total_return_rows,
    COUNT(DISTINCT invoice_no)         AS return_invoices,
    ROUND(SUM(line_revenue), 2)        AS total_return_value,
    ROUND(ABS(SUM(line_revenue)), 2)   AS absolute_return_value
FROM fact_returns;

-- 16B: Breakdown by return_flag
SELECT
    return_flag,
    COUNT(*)                           AS row_count,
    COUNT(DISTINCT invoice_no)         AS invoice_count,
    ROUND(SUM(line_revenue), 2)        AS total_value,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER () * 100, 2) AS pct_of_returns
FROM fact_returns
GROUP BY return_flag
ORDER BY row_count DESC;

-- 16C: Cancellation rate (C-invoice orders / total orders)
SELECT
    (SELECT COUNT(DISTINCT invoice_no) FROM fact_sales)  AS total_sales_orders,
    (SELECT COUNT(DISTINCT invoice_no)
     FROM fact_returns
     WHERE return_flag LIKE '%C_invoice%')                AS cancelled_invoices,
    ROUND(
        (SELECT COUNT(DISTINCT invoice_no)
         FROM fact_returns
         WHERE return_flag LIKE '%C_invoice%')
        / (SELECT COUNT(DISTINCT invoice_no) FROM fact_sales) * 100, 2
    )                                                     AS cancellation_rate_pct;

-- 16D: Monthly cancellation trend
SELECT
    d.year_month,
    COUNT(DISTINCT r.invoice_no)       AS cancelled_invoices,
    ROUND(ABS(SUM(r.line_revenue)), 2) AS cancelled_value
FROM fact_returns r
JOIN dim_date d ON r.date_key = d.date_key
WHERE r.return_flag LIKE '%C_invoice%'
GROUP BY d.year_month
ORDER BY d.year_month;


-- ============================================================
-- Q17: PRODUCT RETURN EXPOSURE
-- ============================================================
-- Formula : For each product, compare sales volume to return volume.
--           Return exposure = return quantity / sales quantity × 100.
-- Business: Identify products with high return rates — quality or
--           description issues.
-- Edge case: Products that appear only in returns (no sales) will
--            have infinite return rate. Use LEFT JOIN + COALESCE.
--            Minimum sales filter applied (≥ 50 units sold).
-- SQL features: CTE, LEFT JOIN, COALESCE, CASE

WITH product_sales AS (
    SELECT
        stock_code,
        SUM(quantity)                 AS units_sold,
        ROUND(SUM(line_revenue), 2)  AS sales_revenue,
        COUNT(DISTINCT invoice_no)   AS sales_orders
    FROM fact_sales
    GROUP BY stock_code
),
product_returns AS (
    SELECT
        stock_code,
        SUM(ABS(quantity))            AS units_returned,
        ROUND(ABS(SUM(line_revenue)), 2) AS return_value,
        COUNT(DISTINCT invoice_no)   AS return_invoices
    FROM fact_returns
    WHERE return_flag IN ('C_invoice', 'negative_quantity', 'C_invoice|negative_quantity')
    GROUP BY stock_code
)
SELECT
    ps.stock_code,
    p.description,
    ps.units_sold,
    ps.sales_revenue,
    COALESCE(pr.units_returned, 0)     AS units_returned,
    COALESCE(pr.return_value, 0)       AS return_value,
    ROUND(
        COALESCE(pr.units_returned, 0) / ps.units_sold * 100, 2
    ) AS return_rate_pct
FROM product_sales ps
JOIN dim_products p ON ps.stock_code = p.stock_code
LEFT JOIN product_returns pr ON ps.stock_code = pr.stock_code
WHERE ps.units_sold >= 50
ORDER BY return_rate_pct DESC
LIMIT 20;


-- ============================================================
-- Q18: MONTH-OVER-MONTH (MoM) REVENUE GROWTH
-- ============================================================
-- Formula : (current_month - prev_month) / prev_month × 100.
-- Business: Growth momentum — accelerating or decelerating.
-- Edge case: First month has no prior month → NULL growth.
--            Partial months (Dec 2010, Dec 2011) will show
--            misleading growth/decline.
-- SQL features: CTE, LAG() window function

WITH monthly AS (
    SELECT
        d.year_month,
        ROUND(SUM(s.line_revenue), 2) AS revenue
    FROM fact_sales s
    JOIN dim_date d ON s.date_key = d.date_key
    GROUP BY d.year_month
    ORDER BY d.year_month
)
SELECT
    year_month,
    revenue                AS current_revenue,
    LAG(revenue) OVER (ORDER BY year_month)    AS prev_revenue,
    revenue - LAG(revenue) OVER (ORDER BY year_month) AS abs_change,
    CASE
        WHEN LAG(revenue) OVER (ORDER BY year_month) IS NULL THEN NULL
        WHEN LAG(revenue) OVER (ORDER BY year_month) = 0     THEN NULL
        ELSE ROUND(
            (revenue - LAG(revenue) OVER (ORDER BY year_month))
            / LAG(revenue) OVER (ORDER BY year_month) * 100, 2
        )
    END AS mom_growth_pct
FROM monthly
ORDER BY year_month;


-- ============================================================
-- Q19: REVENUE CONTRIBUTION BY PRODUCT (Pareto / 80-20)
-- ============================================================
-- Formula : Cumulative % of revenue by product, ranked descending.
-- Business: Pareto analysis — what fraction of products drives 80% of revenue.
-- Edge case: Very long tail of low-revenue products.
-- SQL features: CTE, SUM() OVER (window frame), cumulative %

WITH product_rev AS (
    SELECT
        s.stock_code,
        p.description,
        ROUND(SUM(s.line_revenue), 2) AS product_revenue
    FROM fact_sales s
    JOIN dim_products p ON s.stock_code = p.stock_code
    GROUP BY s.stock_code, p.description
),
ranked AS (
    SELECT
        stock_code,
        description,
        product_revenue,
        ROW_NUMBER() OVER (ORDER BY product_revenue DESC) AS rank_num,
        ROUND(
            product_revenue / SUM(product_revenue) OVER () * 100, 4
        ) AS pct_of_total,
        ROUND(
            SUM(product_revenue) OVER (ORDER BY product_revenue DESC
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            / SUM(product_revenue) OVER () * 100, 2
        ) AS cumulative_pct
    FROM product_rev
)
SELECT *
FROM ranked
WHERE cumulative_pct <= 80
   OR rank_num <= 20   -- always show at least top 20
ORDER BY rank_num;

-- Count of products needed for 80% of revenue:
WITH product_rev AS (
    SELECT stock_code, SUM(line_revenue) AS rev
    FROM fact_sales GROUP BY stock_code
),
cumul AS (
    SELECT stock_code, rev,
        SUM(rev) OVER (ORDER BY rev DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
        / SUM(rev) OVER () * 100 AS cum_pct
    FROM product_rev
)
SELECT
    COUNT(*) AS products_for_80pct,
    (SELECT COUNT(DISTINCT stock_code) FROM fact_sales) AS total_products,
    ROUND(COUNT(*) / (SELECT COUNT(DISTINCT stock_code) FROM fact_sales) * 100, 2)
        AS pct_of_catalog
FROM cumul WHERE cum_pct <= 80;


-- ============================================================
-- Q20: REVENUE CONTRIBUTION BY COUNTRY
-- ============================================================
-- Formula : Country revenue as % of total, with cumulative %.
-- Business: Understand geographic concentration and diversification.
-- Edge case: UK dominates (typically 80%+). Uses denormalized country
--            column in fact_sales — includes anonymous customers.
-- SQL features: CTE, window functions, cumulative sum

WITH country_rev AS (
    SELECT
        country,
        COUNT(DISTINCT invoice_no)     AS orders,
        COUNT(DISTINCT customer_id)    AS customers,
        ROUND(SUM(line_revenue), 2)    AS revenue
    FROM fact_sales
    GROUP BY country
)
SELECT
    country,
    orders,
    customers,
    revenue,
    ROUND(revenue / SUM(revenue) OVER () * 100, 2)  AS pct_of_total,
    ROUND(
        SUM(revenue) OVER (ORDER BY revenue DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
        / SUM(revenue) OVER () * 100, 2
    ) AS cumulative_pct
FROM country_rev
ORDER BY revenue DESC;


-- ============================================================
-- Q21: CUSTOMER REVENUE RANKING
-- ============================================================
-- Formula : Total revenue per customer, ranked descending.
-- Business: Identify VIP customers for loyalty programs.
-- Edge case: Excludes anonymous customers (cannot rank unknowns).
--            customer_id IS NOT NULL.
-- SQL features: CTE, RANK(), PERCENT_RANK(), NTILE()

WITH customer_rev AS (
    SELECT
        s.customer_id,
        dc.country,
        COUNT(DISTINCT s.invoice_no)    AS orders,
        SUM(s.quantity)                  AS units,
        ROUND(SUM(s.line_revenue), 2)   AS total_revenue,
        MIN(d.full_date)                 AS first_purchase,
        MAX(d.full_date)                 AS last_purchase
    FROM fact_sales s
    JOIN dim_customers dc ON s.customer_id = dc.customer_id
    JOIN dim_date d ON s.date_key = d.date_key
    WHERE s.customer_id IS NOT NULL
    GROUP BY s.customer_id, dc.country
)
SELECT
    customer_id,
    country,
    orders,
    units,
    total_revenue,
    first_purchase,
    last_purchase,
    RANK() OVER (ORDER BY total_revenue DESC)       AS revenue_rank,
    ROUND(PERCENT_RANK() OVER (ORDER BY total_revenue ASC) * 100, 2) AS percentile,
    NTILE(10) OVER (ORDER BY total_revenue DESC)    AS decile,
    ROUND(
        total_revenue / SUM(total_revenue) OVER () * 100, 4
    ) AS pct_of_total_revenue
FROM customer_rev
ORDER BY total_revenue DESC
LIMIT 50;

-- Top 10% of customers and their revenue share:
WITH customer_rev AS (
    SELECT
        customer_id,
        SUM(line_revenue) AS total_revenue,
        NTILE(10) OVER (ORDER BY SUM(line_revenue) DESC) AS decile
    FROM fact_sales
    WHERE customer_id IS NOT NULL
    GROUP BY customer_id
)
SELECT
    decile,
    COUNT(*)                             AS customers,
    ROUND(SUM(total_revenue), 2)         AS decile_revenue,
    ROUND(
        SUM(total_revenue) / SUM(SUM(total_revenue)) OVER () * 100, 2
    ) AS pct_of_total
FROM customer_rev
GROUP BY decile
ORDER BY decile;


-- ============================================================
-- END OF ANALYSIS QUERIES
-- ============================================================
-- Total: 21 queries (plus sub-queries and variants)
--
-- Summary of SQL features used:
--   • CTEs (WITH ... AS)        — Q9, Q12-Q21
--   • Window functions          — Q7, Q8, Q10, Q14-Q21
--     - RANK(), ROW_NUMBER()    — Q7, Q8, Q19, Q21
--     - NTILE()                 — Q15, Q21
--     - LAG()                   — Q18
--     - SUM() OVER()            — Q10, Q19, Q20, Q21
--     - PERCENT_RANK()          — Q21
--   • CASE WHEN                 — Q3, Q12-Q16
--   • Aggregate functions       — All queries
--   • JOINs (INNER, LEFT)       — Q5-Q12, Q15-Q21
--   • Date functions            — Q15, Q18
--     - DATEDIFF() (MySQL)
--   • HAVING                    — Q9
--   • Subqueries                — Q16C
-- ============================================================
