# Tableau Dashboard Build Guide
## E-Commerce Sales Intelligence & Customer Behavior Analytics

This guide provides complete, production-ready specifications for building **three enterprise Tableau dashboards** from the cleaned e-commerce dataset. Every calculated field, chart shelf placement, filter configuration, color code, tooltip template, and dashboard layout is documented with exact precision.

---

## 📑 Table of Contents
1. [Architecture & Data Connection Workflows](#1-architecture--data-connection-workflows)
   - [Workflow A: SQL Database → Tableau Desktop](#workflow-a-sql-database--tableau-desktop)
   - [Workflow B: Cleaned CSVs → Tableau Public](#workflow-b-cleaned-csvs--tableau-public)
   - [Data Modeling & Preventing Join Duplication](#data-modeling--preventing-join-duplication)
2. [Master Calculated Fields Library](#2-master-calculated-fields-library)
3. [Dashboard 1: Executive Sales Overview](#3-dashboard-1-executive-sales-overview)
4. [Dashboard 2: Customer Intelligence & Behavior](#4-dashboard-2-customer-intelligence--behavior)
5. [Dashboard 3: Product Intelligence & Returns Analysis](#5-dashboard-3-product-intelligence--returns-analysis)
6. [Dashboard Layouts & Interactivity Actions](#6-dashboard-layouts--interactivity-actions)
7. [Publishing, Verification & Presentation Checklist](#7-publishing-verification--presentation-checklist)

---

## 1. Architecture & Data Connection Workflows

### Workflow A: SQL Database → Tableau Desktop
*Recommended for enterprise deployments with live database connectivity.*

1. Launch **Tableau Desktop**.
2. Under **Connect → To a Server**, select **MySQL** (or **PostgreSQL**).
3. Enter your connection credentials:
   - **Server**: `localhost`
   - **Port**: `3306` (or `5432` for PostgreSQL)
   - **Database**: `ecommerce_analytics`
   - **Username**: `root` (or your DB user)
   - **Password**: *(Your database password)*
4. Drag tables into the canvas using **Tableau Logical Relationships (Noodles)**:
   - Place `fact_sales` in the center.
   - Relate `dim_date` on `date_key = date_key`.
   - Relate `dim_products` on `stock_code = stock_code`.
   - Relate `dim_customers` on `customer_id = customer_id`.
   - Relate `customer_rfm` on `customer_id = customer_id`.
5. Connect `fact_returns` as an **independent logical table** (or relate on `date_key = date_key` and `stock_code = stock_code`).

### Workflow B: Cleaned CSVs → Tableau Public
*Recommended for free Tableau Public users and standalone portfolio submissions.*

1. Launch **Tableau Public** (or Tableau Desktop).
2. Under **Connect → To a File**, select **Text file**.
3. Navigate to `ecommerce-sales-analytics/data/` and select:
   - Primary source: `cleaned_sales.csv`
4. Add additional connections within the same data source:
   - Click **Add** next to Connections → select **Text file** → add `customer_rfm.csv`.
   - Click **Add** → select **Text file** → add `returns_analysis.csv`.
5. Define Relationships in the Logical Layer:
   - `cleaned_sales.csv` ↔ `customer_rfm.csv`:
     - Relationship field: `customer_id = customer_id`
     - Cardinality: Many-to-One
   - `cleaned_sales.csv` ↔ `returns_analysis.csv`:
     - **DO NOT create a physical join!** Relate via the logical layer on `invoice_date = invoice_date` AND `stock_code = stock_code`, OR keep `returns_analysis.csv` as a separate data source and use Tableau Dashboard Filter Actions.

---

### Data Modeling & Preventing Join Duplication

> [!CAUTION]
> **The Join Fanout Trap:** If you execute a physical `INNER JOIN` or `LEFT JOIN` between `cleaned_sales.csv` and `returns_analysis.csv` on `customer_id` or `stock_code`, a customer with 10 sales and 5 returns will produce $10 \times 5 = 50$ rows. This inflates revenue and transaction counts by orders of magnitude.

**How Tableau's Logical Layer Solves This:**
- Tableau 2020.2+ introduces **Relationships** (the "noodles" in the data canvas). Unlike physical joins, relationships query each table at its own native Level of Detail (LOD).
- When you drag `[line_revenue]` from `cleaned_sales`, Tableau issues `SELECT SUM(line_revenue) FROM cleaned_sales`.
- It does **not** join the tables until fields from both tables appear on the same visualization shelf, and even then, aggregates before joining.
- **Rule for Calculated Fields:** Always use distinct counts (`COUNTD([invoice_no])`, `COUNTD([customer_id])`) rather than row counts (`SUM(Number of Records)` or `COUNT()`).

---

## 2. Master Calculated Fields Library

Copy and paste these exact formulas into Tableau by navigating to **Analysis → Create Calculated Field**.

### 1. Total Gross Revenue
- **Name**: `Total Gross Revenue`
- **Formula**:
  ```tableau
  SUM([line_revenue])
  ```
- **Default Format**: Currency (Standard) → Prefix `$`, 0 decimals (or 2 decimals for cards).

### 2. Total Orders
- **Name**: `Total Orders`
- **Formula**:
  ```tableau
  COUNTD([invoice_no])
  ```
- **Default Format**: Number (Standard) → `#,##0`.

### 3. Total Identified Customers
- **Name**: `Total Identified Customers`
- **Formula**:
  ```tableau
  COUNTD([customer_id])
  ```
- **Default Format**: Number (Standard) → `#,##0`.

### 4. Total Units Sold
- **Name**: `Total Units Sold`
- **Formula**:
  ```tableau
  SUM([quantity])
  ```
- **Default Format**: Number (Standard) → `#,##0`.

### 5. Average Order Value (AOV)
- **Name**: `Average Order Value`
- **Formula**:
  ```tableau
  [Total Gross Revenue] / [Total Orders]
  ```
- **Default Format**: Currency (Custom) → `$#,##0.00`.

### 6. MoM Revenue Growth %
- **Name**: `MoM Revenue Growth %`
- **Formula**:
  ```tableau
  (ZN([Total Gross Revenue]) - LOOKUP(ZN([Total Gross Revenue]), -1)) 
  / ABS(LOOKUP(ZN([Total Gross Revenue]), -1))
  ```
- **Default Format**: Percentage → `+0.0%;-0.0%;0.0%`.

### 7. Customer Order Count (LOD)
- **Name**: `Customer Order Count (LOD)`
- **Formula**:
  ```tableau
  { FIXED [customer_id] : COUNTD([invoice_no]) }
  ```
- **Comment**: Computes order frequency per customer regardless of sheet-level dimensions.

### 8. Is Repeat Customer
- **Name**: `Is Repeat Customer`
- **Formula**:
  ```tableau
  IF ISNULL([customer_id]) THEN 
      "Anonymous / Guest"
  ELSEIF [Customer Order Count (LOD)] >= 2 THEN 
      "Repeat Customer"
  ELSE 
      "One-Time Customer"
  END
  ```
- **Data Type**: String.

### 9. Customer Repeat Rate %
- **Name**: `Customer Repeat Rate %`
- **Formula**:
  ```tableau
  COUNTD(IF [Customer Order Count (LOD)] >= 2 THEN [customer_id] END) 
  / COUNTD([customer_id])
  ```
- **Default Format**: Percentage → `0.00%`.

### 10. Customer First Purchase Date (LOD)
- **Name**: `Customer First Purchase Date (LOD)`
- **Formula**:
  ```tableau
  { FIXED [customer_id] : MIN([invoice_date]) }
  ```
- **Data Type**: Date.

### 11. Customer Cohort (Month)
- **Name**: `Customer Cohort (Month)`
- **Formula**:
  ```tableau
  DATETRUNC('month', [Customer First Purchase Date (LOD)])
  ```
- **Data Type**: Date.

### 12. Return Value (Absolute)
- **Name**: `Return Value (Absolute)`
- **Formula**:
  ```tableau
  ABS(SUM([line_revenue]))
  ```
- **Default Format**: Currency → `$#,##0.00`. (Used for `returns_analysis.csv` or `fact_returns`).

### 13. Cancellation Rate %
- **Name**: `Cancellation Rate %`
- **Formula**:
  ```tableau
  COUNTD(IF CONTAINS([return_flag], "C_invoice") THEN [invoice_no] END) 
  / COUNTD([invoice_no])
  ```
- **Default Format**: Percentage → `0.00%`.

### 14. Revenue Share % (Table Calc)
- **Name**: `Revenue Share %`
- **Formula**:
  ```tableau
  SUM([line_revenue]) / TOTAL(SUM([line_revenue]))
  ```
- **Default Format**: Percentage → `0.0%`.

---

## 3. Dashboard 1: Executive Sales Overview

### Purpose & Persona
**Target Audience:** Chief Executive Officer, VP of Sales, General Management.  
**Objective:** Deliver an immediate snapshot of top-line commercial health, monthly revenue trends, geographic expansion, and high-velocity SKUs.

### Canvas Specifications
- **Size:** Fixed 1366 × 768 px (Standard Laptop) or 1440 × 900 px.
- **Theme:** Clean Modern Light theme with a dark slate header bar (`#1E293B`).
- **Font Family:** Arial / Segoe UI.

---

### Sheet 1.1: Executive KPI Scorecards
- **Chart Type:** Text Card (KPI Blocks)
- **Shelves:**
  - **Rows:** None
  - **Columns:** `Measure Names`
  - **Text (Label):** `Measure Values`
  - **Filters:** `Measure Names` restricted to:
    1. `Total Gross Revenue`
    2. `Total Orders`
    3. `Total Identified Customers`
    4. `Average Order Value`
    5. `Total Units Sold`
- **Formatting:**
  - Font size for Numbers: 22pt Bold (`#0F172A`).
  - Font size for Labels: 9pt Uppercase Regular (`#64748B`).
  - Card background: `#F8FAFC` with 1px border `#E2E8F0`.
- **Tooltip:** "Executive KPI: <Measure Names> is <Measure Values> across the selected date range."

---

### Sheet 1.2: Monthly Revenue & MoM Growth Dual-Axis Trend
- **Chart Type:** Dual-Axis Combination (Bar + Line with Data Points)
- **Shelves:**
  - **Columns:** `YEAR([invoice_date])` + `MONTH([invoice_date])` (Continuous Date)
  - **Rows (Primary):** `[Total Gross Revenue]` (Mark: **Bar**)
  - **Rows (Secondary):** `[MoM Revenue Growth %]` (Mark: **Line**)
- **Configuration:**
  - Right-click secondary pill on Rows → check **Dual Axis**.
  - Right-click secondary axis header on chart → click **Synchronize Axis** (adjust scales as appropriate for currency vs percentage).
  - Primary Bar Color: Navy Blue (`#1E3A8A`), 80% opacity.
  - Secondary Line Color: Coral Red (`#F97316`), 2.5px thickness, marker enabled.
  - Add a **Zero Reference Line** on the secondary growth axis (`Value = 0`).
- **Tooltip:**
  ```text
  Month: <YEAR(invoice_date)> <MONTH(invoice_date)>
  Gross Revenue: <SUM(line_revenue)>
  MoM Growth: <[MoM Revenue Growth %]>
  Total Orders: <COUNTD(invoice_no)>
  ```

---

### Sheet 1.3: Geographic Sales Distribution (Choropleth Map)
- **Chart Type:** Filled Map (Choropleth)
- **Shelves:**
  - **Marks Card:** Map
  - **Detail:** `[country]` (ensure Geographic Role = Country/Region)
  - **Color:** `[Total Gross Revenue]` (Color palette: **Blue-Teal Sequential**, 5 steps)
  - **Size / Detail:** `[Total Orders]`
- **Formatting:**
  - Map Layers: Light background layer, coastlines visible, wash-out at 15%.
  - Border: Thin white border `#FFFFFF` around countries.
- **Tooltip:**
  ```text
  Country: <country>
  Gross Sales: <SUM(line_revenue)>
  Total Orders: <COUNTD(invoice_no)>
  AOV: <[Average Order Value]>
  % of Global Revenue: <[Revenue Share %]>
  ```

---

### Sheet 1.4: Top 10 Revenue-Generating Products
- **Chart Type:** Horizontal Bar Chart
- **Shelves:**
  - **Rows:** `[description]`
  - **Columns:** `[Total Gross Revenue]`
  - **Filters:** 
    - `[description]` → **Top** tab → By Field: **Top 10** by `[Total Gross Revenue]` Sum.
    - Exclude `NULL` or generic descriptions.
- **Sorting:** Sort `[description]` descending by `[Total Gross Revenue]`.
- **Marks Card:**
  - Color: `#0284C7` (Sky Blue gradient).
  - Label: `[Total Gross Revenue]` enabled, position right of bar.
- **Tooltip:**
  ```text
  Product: <description>
  Stock Code: <stock_code>
  Gross Revenue: <SUM(line_revenue)>
  Units Sold: <SUM(quantity)>
  Average Price: <AVG(unit_price)>
  ```

---

### Sheet 1.5: Weekly Order Heatmap (Day of Week vs Time)
- **Chart Type:** Heatmap (Square Mark)
- **Shelves:**
  - **Columns:** `DATEPART('weekday', [invoice_date])` (Discrete: Sun, Mon, ..., Sat)
  - **Rows:** `DATEPART('hour', [invoice_date])` (Discrete: 6 AM to 8 PM)
  - **Color:** `COUNTD([invoice_no])` (Palette: **Orange Sequential**)
- **Marks Card:** Shape / Square.
- **Tooltip:**
  ```text
  Day: <DATEPART('weekday', invoice_date)>
  Hour: <DATEPART('hour', invoice_date)>:00
  Order Volume: <COUNTD(invoice_no)>
  ```

---

## 4. Dashboard 2: Customer Intelligence & Behavior

### Purpose & Persona
**Target Audience:** Chief Marketing Officer, CRM Director, Customer Retention Leads.  
**Objective:** Dissect customer acquisition cohorts, track repeat buying behavior, and visualize RFM customer segment distribution.

---

### Sheet 2.1: Customer Health Scorecards
- **Chart Type:** KPI Banner
- **Metrics Displayed:**
  1. `Total Identified Customers` (e.g., 4,338)
  2. `Customer Repeat Rate %` (Target: > 60%)
  3. `Average Lifetime Spend` (`SUM([line_revenue]) / COUNTD([customer_id])`)
  4. `Champions Segment Share %`

---

### Sheet 2.2: RFM Customer Segment Treemap
- **Chart Type:** Treemap
- **Shelves:**
  - **Marks Card:** Automatic / Square
  - **Detail:** `[rfm_segment]` (from `customer_rfm.csv`)
  - **Size:** `COUNTD([customer_id])`
  - **Color:** `[rfm_segment]`
  - **Label:** `[rfm_segment]`, `COUNTD([customer_id])`, `[Revenue Share %]`
- **Color Palette Specification:**
  - **Champions**: Emerald Green (`#059669`)
  - **Loyal Customers**: Deep Blue (`#2563EB`)
  - **Potential Loyalists**: Cyan (`#06B6D4`)
  - **New Customers**: Light Blue (`#38BDF8`)
  - **Promising**: Teal (`#14B8A6`)
  - **Need Attention**: Amber (`#F59E0B`)
  - **About to Sleep**: Warm Orange (`#FB923C`)
  - **At Risk**: Crimson Red (`#DC2626`)
  - **Cant Lose Them**: Violet / Purple (`#7C3AED`)
  - **Lost**: Slate Gray (`#64748B`)
- **Tooltip:**
  ```text
  Segment: <rfm_segment>
  Customer Count: <COUNTD(customer_id)> (<% of Total Customers>)
  Total Revenue: <SUM(monetary_revenue)> (<% of Total Revenue>)
  Average Recency: <AVG(recency_days)> days
  Average Frequency: <AVG(frequency_orders)> orders
  Average Lifetime Spend: <AVG(monetary_revenue)>
  ```

---

### Sheet 2.3: RFM Value vs Frequency Scatter Matrix
- **Chart Type:** Scatter Plot with Reference Bands
- **Shelves:**
  - **Columns:** `[frequency_orders]` (Logarithmic scale recommended for wide distributions)
  - **Rows:** `[monetary_revenue]` (Logarithmic scale)
  - **Detail:** `[customer_id]`
  - **Color:** `[rfm_segment]` (matching palette above)
  - **Size:** `[total_units]` (optional)
- **Analytics Pane Annotations:**
  - Add **Median Line** on X-Axis (`Frequency`).
  - Add **Median Line** on Y-Axis (`Monetary Revenue`).
  - This partitions the space into 4 behavioral quadrants (High Freq/High Spend, High Freq/Low Spend, etc.).
- **Tooltip:**
  ```text
  Customer ID: <customer_id>
  Segment: <rfm_segment>
  Country: <country>
  Total Orders: <frequency_orders>
  Lifetime Revenue: <monetary_revenue>
  Days Since Last Order: <recency_days>
  RFM Score: <rfm_score>
  ```

---

### Sheet 2.4: New vs Repeat Customer Revenue Trend
- **Chart Type:** 100% Stacked Bar Chart
- **Shelves:**
  - **Columns:** `DATETRUNC('month', [invoice_date])`
  - **Rows:** `[Total Gross Revenue]`
  - **Color:** `[Is Repeat Customer]`
  - **Table Calculation:** Right-click Rows pill → **Quick Table Calculation → Percent of Total** → Compute Using **Table (down)**.
- **Colors:**
  - Repeat Customer: Royal Blue (`#1D4ED8`)
  - One-Time Customer: Sky Blue (`#93C5FD`)
  - Anonymous / Guest: Neutral Gray (`#CBD5E1`)
- **Tooltip:**
  ```text
  Month: <invoice_date>
  Cohort Type: <Is Repeat Customer>
  Revenue: <SUM(line_revenue)>
  Percentage of Monthly Sales: <SUM(line_revenue) % of Total>
  ```

---

### Sheet 2.5: Customer Purchase Frequency Distribution
- **Chart Type:** Histogram / Discrete Bar Chart
- **Shelves:**
  - **Columns:** `[Customer Order Count (LOD)]` (Discrete dimension: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11+)
  - **Rows:** `COUNTD([customer_id])`
  - **Label:** `COUNTD([customer_id])` and `% of Total Customers`
  - **Color:** `#475569` (Dark Slate).
- **Tooltip:**
  ```text
  Orders Placed: <Customer Order Count (LOD)>
  Number of Customers: <COUNTD(customer_id)>
  Percentage of Total Base: <COUNTD(customer_id) % of Total>
  ```

---

## 5. Dashboard 3: Product Intelligence & Returns Analysis

### Purpose & Persona
**Target Audience:** Category Managers, Supply Chain Directors, Quality Assurance Leads.  
**Objective:** Identify profit drivers, pinpoint products with excessive return/cancellation rates, and uncover margin leakage.

---

### Sheet 3.1: Quality & Return Loss KPIs
- **Chart Type:** KPI Banner
- **Metrics Displayed:**
  1. `Total Return / Cancellation Value` (`ABS(SUM([line_revenue]))` from `returns_analysis.csv`)
  2. `Total Cancelled Transactions` (`COUNTD([invoice_no])` where `return_flag LIKE '%C_invoice%'`)
  3. `Overall Cancellation Rate %` (`[Cancellation Rate %]`)
  4. `Products with > 10% Return Rate`

---

### Sheet 3.2: Product Revenue vs Return Exposure Quadrant Matrix
- **Chart Type:** Scatter Plot with Quadrant Shading
- **Shelves:**
  - **Columns:** `SUM([quantity])` (Sales Volume)
  - **Rows:** `[Cancellation Rate %]` (or Return Exposure Ratio)
  - **Detail:** `[stock_code]`, `[description]`
  - **Color:** `[Cancellation Rate %]` (Sequential **Red-Amber-Green Reverted**)
  - **Size:** `[Total Gross Revenue]`
- **Filter Shelf:** 
  - `SUM([quantity])` >= 50 units (filters out low-volume statistical noise).
- **Analytics Annotations (4 Quadrants):**
  - Quadrant 1 (High Sales, Low Returns): **Core Heroes / Cash Cows** (Promote aggressively)
  - Quadrant 2 (High Sales, High Returns): **Quality Alert / Sizing Issues** (Inspect vendor/description)
  - Quadrant 3 (Low Sales, High Returns): **Discontinue / Liquidation Candidates**
  - Quadrant 4 (Low Sales, Low Returns): **Niche Long-Tail**
- **Tooltip:**
  ```text
  Product: <description>
  Stock Code: <stock_code>
  Gross Sales: <SUM(line_revenue)>
  Units Sold: <SUM(quantity)>
  Cancellation Rate: <[Cancellation Rate %]>
  Quadrant: <Product Action Classification>
  ```

---

### Sheet 3.3: Cancellation & Return Reason Breakdown
- **Chart Type:** Donut Chart or Horizontal Stacked Bar
- **Shelves (Horizontal Bar):**
  - **Rows:** `[return_flag]`
  - **Columns:** `ABS(SUM([line_revenue]))` and `COUNTD([invoice_no])`
  - **Color:** `[return_flag]` (Palette: Dark Orange to Deep Crimson)
  - **Label:** `ABS(SUM([line_revenue]))` and `% of Total Returns`
- **Tooltip:**
  ```text
  Classification: <return_flag>
  Cancelled Orders: <COUNTD(invoice_no)>
  Financial Impact: <ABS(SUM(line_revenue))>
  % of Total Non-Sale Transactions: <SUM(line_revenue) % of Total>
  ```

---

### Sheet 3.4: Pareto Cumulative Revenue Analysis (80/20 Rule)
- **Chart Type:** Dual-Axis Line and Bar Chart
- **Shelves:**
  - **Columns:** `[description]` (Sorted descending by `[Total Gross Revenue]`)
  - **Rows (Primary):** `[Total Gross Revenue]` (Mark: Bar)
  - **Rows (Secondary):** `RUNNING_SUM(SUM([line_revenue])) / TOTAL(SUM([line_revenue]))` (Mark: Line)
- **Configuration:**
  - Secondary Axis: Format as Percentage (0% to 100%).
  - Add **Constant Reference Line** at `80.0%` on the secondary axis.
  - This visually proves what % of products generate 80% of total revenue.
- **Tooltip:**
  ```text
  Product Rank: <INDEX()>
  Product: <description>
  Revenue: <SUM(line_revenue)>
  Cumulative Revenue Share: <Running % of Total>
  ```

---

## 6. Dashboard Layouts & Interactivity Actions

### Layout Grid Architecture (1366 × 768 px)

```
┌────────────────────────────────────────────────────────────────────────┐
│  HEADER: Title | Last Updated | Global Filters (Date, Country, Cohort)  │
├────────────────────────────────────────────────────────────────────────┤
│  ROW 1: KPI Scorecard Containers (4 or 5 equal-width metric cards)     │
├──────────────────────────────────┬─────────────────────────────────────┤
│  ROW 2 (LEFT, 60% Width):        │  ROW 2 (RIGHT, 40% Width):          │
│  Primary Time-Series / Treemap   │  Top Products / Segment Breakdown   │
├──────────────────────────────────┼─────────────────────────────────────┤
│  ROW 3 (LEFT, 50% Width):        │  ROW 3 (RIGHT, 50% Width):          │
│  Geographic Map / Scatter Matrix │  Cohort Stacked Bar / Distribution  │
└──────────────────────────────────┴─────────────────────────────────────┘
```

### Dashboard Interactivity Actions

Configure these actions under **Dashboard → Actions (Ctrl+Shift+A)**:

#### 1. Filter Action: Country Cross-Filter (Executive Dashboard)
- **Source Sheet:** `Sheet 1.3: Geographic Sales Map`
- **Target Sheets:** All other sheets on Dashboard 1
- **Run Action on:** `Select`
- **Clearing Selection:** `Show all values`
- **Effect:** Clicking the United Kingdom, Germany, or France filters the Monthly Trend, Top Products, and KPI cards to that country.

#### 2. Filter Action: RFM Segment Deep-Dive (Customer Dashboard)
- **Source Sheet:** `Sheet 2.2: RFM Customer Segment Treemap`
- **Target Sheets:** `Sheet 2.3: Scatter Matrix` and `Sheet 2.4: Cohort Bar`
- **Run Action on:** `Select`
- **Clearing Selection:** `Show all values`
- **Effect:** Clicking "Champions" isolates their scatter distribution and cohort history.

#### 3. Highlight Action: Product Category / SKU Inspector
- **Source Sheet:** `Sheet 3.4: Pareto Curve`
- **Target Sheets:** `Sheet 3.2: Quadrant Matrix`
- **Run Action on:** `Hover`
- **Target Fields:** `[stock_code]`

---

## 7. Publishing, Verification & Presentation Checklist

### Pre-Publishing Audit
- [ ] **Data Validation:** Compare Tableau Total Gross Revenue, Orders, and Customers with [validate_metrics.py](file:///c:/Users/panka/Desktop/data%20analytics/ecommerce-sales-analytics/python/validate_metrics.py) outputs. Numbers must match exactly.
- [ ] **No Raw Column Names:** Every pill in tooltips and legends must have clean business labels (e.g., "Gross Sales" instead of `SUM(line_revenue)`).
- [ ] **Currency & Number Formatting:** Every monetary measure formatted with `$` and commas; every rate formatted with `%`.
- [ ] **No Overlapping Labels:** Turn on "Allow labels to overlap other marks" only when strictly required; otherwise use automated placement.
- [ ] **Filter Scope:** Ensure global filters (Date Range, Country) apply to **"All Using Related Data Sources"** or **"All Worksheets on this Dashboard"**.

### Publishing to Tableau Public
1. In Tableau Desktop, go to **Server → Tableau Public → Save to Tableau Public As...**
2. Enter your Tableau Public login credentials.
3. Save as: `E-Commerce Sales Intelligence & Customer Behavior Analytics`.
4. In browser settings on Tableau Public:
   - Check **"Allow others to download or inspect this workbook"** (recommended for portfolio evaluation).
   - Verify mobile layout rendering.
5. Take screenshots of all 3 dashboards and save them into the `screenshots/` directory for the final project report.
