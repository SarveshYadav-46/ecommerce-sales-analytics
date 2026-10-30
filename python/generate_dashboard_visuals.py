"""
generate_dashboard_visuals.py — Automated Visual Dashboard Generator
=====================================================================
Renders high-resolution, enterprise-grade analytical dashboard visuals
directly from the real empirical data files (cleaned_sales.csv, customer_rfm.csv,
returns_analysis.csv) and saves them into the screenshots/ directory.

Outputs:
    - screenshots/dashboard1_executive_overview.png
    - screenshots/dashboard2_customer_intel.png
    - screenshots/dashboard3_product_returns.png

Usage:
    cd ecommerce-sales-analytics
    python python/generate_dashboard_visuals.py
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Headless backend
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python"))

from config import PATHS, setup_logging

logger = setup_logging("generate_dashboard_visuals")

# Global aesthetic styling
plt.rcParams["font.sans-serif"] = ["Segoe UI", "DejaVu Sans", "Arial"]
plt.rcParams["axes.edgecolor"] = "#CBD5E1"
plt.rcParams["axes.linewidth"] = 0.8


# ============================================================
# DASHBOARD 1: EXECUTIVE SALES OVERVIEW
# ============================================================

def generate_dashboard1():
    logger.info("Generating Dashboard 1: Executive Sales Overview...")
    sales_path = PATHS["cleaned_sales_csv"]
    df = pd.read_csv(sales_path, parse_dates=["invoice_date"])

    fig = plt.figure(figsize=(16, 9), facecolor="#F8FAFC")
    fig.suptitle("EXECUTIVE SALES INTELLIGENCE & PERFORMANCE OVERVIEW", fontsize=18, fontweight="bold", color="#0F172A", y=0.97)

    # Grid layout: 4 rows, 4 cols
    gs = fig.add_gridspec(3, 3, height_ratios=[0.25, 1, 1], hspace=0.35, wspace=0.25, left=0.06, right=0.95, top=0.91, bottom=0.06)

    # 1. KPI Cards Row (span all 3 cols in row 0)
    kpi_ax = fig.add_subplot(gs[0, :])
    kpi_ax.axis("off")

    kpis = [
        ("GROSS REVENUE", f"${df['line_revenue'].sum():,.2f}", "#0284C7"),
        ("TOTAL ORDERS", f"{df['invoice_no'].nunique():,}", "#0D9488"),
        ("UNIQUE CUSTOMERS", f"{df['customer_id'].dropna().nunique():,}", "#6366F1"),
        ("TOTAL UNITS SOLD", f"{df['quantity'].sum():,}", "#8B5CF6"),
        ("AVERAGE ORDER VALUE", f"${df['line_revenue'].sum() / df['invoice_no'].nunique():,.2f}", "#D97706"),
    ]

    for i, (title, val, color) in enumerate(kpis):
        x = i * 0.20 + 0.01
        rect = plt.Rectangle((x, 0.05), 0.18, 0.85, transform=kpi_ax.transAxes, facecolor="#FFFFFF", edgecolor="#E2E8F0", linewidth=1.2, zorder=2)
        kpi_ax.add_patch(rect)
        kpi_ax.text(x + 0.09, 0.65, title, transform=kpi_ax.transAxes, fontsize=9, fontweight="bold", color="#64748B", ha="center", va="center")
        kpi_ax.text(x + 0.09, 0.32, val, transform=kpi_ax.transAxes, fontsize=15, fontweight="bold", color=color, ha="center", va="center")

    # 2. Monthly Revenue & Growth (Row 1, Cols 0-1)
    ax_trend = fig.add_subplot(gs[1, :2])
    monthly = df.groupby("year_month").agg(revenue=("line_revenue", "sum"), orders=("invoice_no", "nunique")).reset_index()
    monthly["mom_growth"] = monthly["revenue"].pct_change() * 100.0

    ax_trend.set_facecolor("#FFFFFF")
    bars = ax_trend.bar(monthly["year_month"], monthly["revenue"] / 1e3, color="#1E3A8A", alpha=0.85, width=0.55, label="Gross Revenue ($K)")
    ax_trend.set_ylabel("Revenue ($ in Thousands)", fontsize=10, fontweight="bold", color="#1E3A8A")
    ax_trend.tick_params(axis="x", rotation=40, labelsize=9)
    ax_trend.grid(axis="y", linestyle="--", alpha=0.3)

    # Secondary Growth Axis
    ax_growth = ax_trend.twinx()
    ax_growth.plot(monthly["year_month"], monthly["mom_growth"], color="#EA580C", marker="o", linewidth=2.2, label="MoM Growth (%)")
    ax_growth.axhline(0, color="#94A3B8", linestyle=":", linewidth=1)
    ax_growth.set_ylabel("MoM Growth (%)", fontsize=10, fontweight="bold", color="#EA580C")
    ax_trend.set_title("Monthly Gross Sales Velocity & MoM Growth Rate", fontsize=11, fontweight="bold", pad=8, color="#1E293B")

    # 3. Top 8 Countries (Row 1, Col 2)
    ax_country = fig.add_subplot(gs[1, 2])
    ax_country.set_facecolor("#FFFFFF")
    country_rev = df.groupby("country")["line_revenue"].sum().sort_values(ascending=False).head(7)
    country_names = [c if len(c) <= 12 else c[:10] + ".." for c in country_rev.index]
    ax_country.barh(country_names[::-1], country_rev.values[::-1] / 1e3, color="#0284C7", alpha=0.85)
    ax_country.set_xlabel("Gross Sales ($K)", fontsize=9, fontweight="bold")
    ax_country.set_title("Top Regional Markets ($K)", fontsize=11, fontweight="bold", pad=8, color="#1E293B")
    ax_country.grid(axis="x", linestyle="--", alpha=0.3)

    # 4. Top 8 Products by Revenue (Row 2, Cols 0-1)
    ax_prod = fig.add_subplot(gs[2, :2])
    ax_prod.set_facecolor("#FFFFFF")
    top_prod = df.groupby("description")["line_revenue"].sum().sort_values(ascending=False).head(8)
    short_names = [d[:26] + "..." if len(d) > 28 else d for d in top_prod.index]
    bars_p = ax_prod.barh(short_names[::-1], top_prod.values[::-1] / 1e3, color="#0D9488", alpha=0.85)
    ax_prod.set_xlabel("Product Revenue ($ in Thousands)", fontsize=9, fontweight="bold")
    ax_prod.set_title("Top 8 Commercial Drivers by Revenue", fontsize=11, fontweight="bold", pad=8, color="#1E293B")
    ax_prod.grid(axis="x", linestyle="--", alpha=0.3)

    # 5. Order Traffic Heatmap by Hour (Row 2, Col 2)
    ax_hour = fig.add_subplot(gs[2, 2])
    ax_hour.set_facecolor("#FFFFFF")
    df["hour"] = df["invoice_date"].dt.hour
    hour_orders = df.groupby("hour")["invoice_no"].nunique()
    ax_hour.bar(hour_orders.index, hour_orders.values, color="#D97706", alpha=0.85, width=0.7)
    ax_hour.set_xlabel("Hour of Day (24h)", fontsize=9, fontweight="bold")
    ax_hour.set_ylabel("Order Count", fontsize=9, fontweight="bold")
    ax_hour.set_title("Peak Order Volume by Hour", fontsize=11, fontweight="bold", pad=8, color="#1E293B")
    ax_hour.grid(axis="y", linestyle="--", alpha=0.3)

    out_path = PATHS["screenshots_dir"] / "dashboard1_executive_overview.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    logger.info(f"Dashboard 1 saved to: {out_path} ✓")


# ============================================================
# DASHBOARD 2: CUSTOMER INTELLIGENCE & BEHAVIOR
# ============================================================

def generate_dashboard2():
    logger.info("Generating Dashboard 2: Customer Intelligence & Behavior...")
    rfm_path = PATHS["rfm_csv"]
    sales_path = PATHS["cleaned_sales_csv"]
    rfm = pd.read_csv(rfm_path)
    sales = pd.read_csv(sales_path, parse_dates=["invoice_date"])

    fig = plt.figure(figsize=(16, 9), facecolor="#F8FAFC")
    fig.suptitle("CUSTOMER INTELLIGENCE & BEHAVIORAL SEGMENTATION (RFM)", fontsize=18, fontweight="bold", color="#0F172A", y=0.97)

    gs = fig.add_gridspec(3, 3, height_ratios=[0.25, 1, 1], hspace=0.35, wspace=0.25, left=0.06, right=0.95, top=0.91, bottom=0.06)

    # 1. KPI Cards Row
    kpi_ax = fig.add_subplot(gs[0, :])
    kpi_ax.axis("off")

    champs = rfm[rfm["rfm_segment"] == "Champions"]
    loyal = rfm[rfm["rfm_segment"] == "Loyal Customers"]
    repeat_rate = (rfm["frequency_orders"] >= 2).mean() * 100.0

    kpis = [
        ("TOTAL IDENTIFIED", f"{len(rfm):,} Customers", "#2563EB"),
        ("REPEAT PURCHASE RATE", f"{repeat_rate:.2f}%", "#059669"),
        ("CHAMPIONS REVENUE", f"${champs['monetary_revenue'].sum():,.2f}", "#7C3AED"),
        ("CHAMPION REVENUE SHARE", f"{(champs['monetary_revenue'].sum() / rfm['monetary_revenue'].sum()) * 100:.1f}%", "#DC2626"),
        ("AVG CUSTOMER LIFETIME SPEND", f"${rfm['monetary_revenue'].mean():,.2f}", "#D97706"),
    ]

    for i, (title, val, color) in enumerate(kpis):
        x = i * 0.20 + 0.01
        rect = plt.Rectangle((x, 0.05), 0.18, 0.85, transform=kpi_ax.transAxes, facecolor="#FFFFFF", edgecolor="#E2E8F0", linewidth=1.2, zorder=2)
        kpi_ax.add_patch(rect)
        kpi_ax.text(x + 0.09, 0.65, title, transform=kpi_ax.transAxes, fontsize=9, fontweight="bold", color="#64748B", ha="center", va="center")
        kpi_ax.text(x + 0.09, 0.32, val, transform=kpi_ax.transAxes, fontsize=15, fontweight="bold", color=color, ha="center", va="center")

    # 2. RFM Segment Revenue Share (Row 1, Cols 0-1)
    ax_seg = fig.add_subplot(gs[1, :2])
    ax_seg.set_facecolor("#FFFFFF")
    seg_summary = rfm.groupby("rfm_segment").agg(customers=("customer_id", "count"), revenue=("monetary_revenue", "sum")).sort_values(by="revenue", ascending=True)

    colors = ["#059669" if s == "Champions" else ("#2563EB" if s == "Loyal Customers" else ("#DC2626" if "Risk" in s or "Lose" in s else "#64748B")) for s in seg_summary.index]
    bars = ax_seg.barh(seg_summary.index, seg_summary["revenue"] / 1e3, color=colors, alpha=0.9)
    ax_seg.set_xlabel("Segment Revenue ($ in Thousands)", fontsize=10, fontweight="bold")
    ax_seg.set_title("Customer RFM Segment Revenue Distribution (Pareto Impact)", fontsize=11, fontweight="bold", pad=8, color="#1E293B")
    ax_seg.grid(axis="x", linestyle="--", alpha=0.3)

    # Add text labels on bars
    for bar in bars:
        w = bar.get_width()
        ax_seg.text(w + 20, bar.get_y() + bar.get_height() / 2, f"${w:,.1f}K", va="center", fontsize=8.5, color="#334155")

    # 3. Customer Count per Segment (Row 1, Col 2)
    ax_pie = fig.add_subplot(gs[1, 2])
    seg_counts = rfm["rfm_segment"].value_counts()
    ax_pie.pie(seg_counts.values, labels=seg_counts.index, autopct="%1.0f%%", textprops={"fontsize": 8}, colors=plt.cm.tab10.colors)
    ax_pie.set_title("Customer Population by Segment", fontsize=11, fontweight="bold", pad=8, color="#1E293B")

    # 4. Log-Scale Frequency vs Monetary Scatter (Row 2, Cols 0-1)
    ax_scatter = fig.add_subplot(gs[2, :2])
    ax_scatter.set_facecolor("#FFFFFF")
    ax_scatter.scatter(rfm["frequency_orders"], rfm["monetary_revenue"], c=rfm["r_score"], cmap="viridis", alpha=0.6, edgecolors="none", s=25)
    ax_scatter.set_xscale("log")
    ax_scatter.set_yscale("log")
    ax_scatter.axvline(rfm["frequency_orders"].median(), color="#DC2626", linestyle="--", linewidth=1.2, label=f"Median Freq: {rfm['frequency_orders'].median():.0f}")
    ax_scatter.axhline(rfm["monetary_revenue"].median(), color="#2563EB", linestyle="--", linewidth=1.2, label=f"Median Spend: ${rfm['monetary_revenue'].median():,.0f}")
    ax_scatter.set_xlabel("Order Frequency (Log Scale)", fontsize=9, fontweight="bold")
    ax_scatter.set_ylabel("Monetary Spend ($ Log Scale)", fontsize=9, fontweight="bold")
    ax_scatter.set_title("Customer Value Matrix: Frequency vs Spend (Color = Recency Score)", fontsize=11, fontweight="bold", pad=8, color="#1E293B")
    ax_scatter.legend(loc="lower right", fontsize=8.5)
    ax_scatter.grid(True, linestyle="--", alpha=0.3)

    # 5. Purchase Frequency Histogram (Row 2, Col 2)
    ax_hist = fig.add_subplot(gs[2, 2])
    ax_hist.set_facecolor("#FFFFFF")
    freq_bins = [1, 2, 3, 5, 10, 20, 250]
    freq_labels = ["1", "2", "3", "4-5", "6-10", "11+"]
    rfm["freq_bucket"] = pd.cut(rfm["frequency_orders"], bins=freq_bins, labels=freq_labels, right=True, include_lowest=True)
    bucket_counts = rfm["freq_bucket"].value_counts()[freq_labels]
    ax_hist.bar(freq_labels, bucket_counts.values, color="#475569", alpha=0.85)
    ax_hist.set_xlabel("Lifetime Orders Placed", fontsize=9, fontweight="bold")
    ax_hist.set_ylabel("Customer Count", fontsize=9, fontweight="bold")
    ax_hist.set_title("Order Frequency Distribution", fontsize=11, fontweight="bold", pad=8, color="#1E293B")
    ax_hist.grid(axis="y", linestyle="--", alpha=0.3)

    out_path = PATHS["screenshots_dir"] / "dashboard2_customer_intel.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    logger.info(f"Dashboard 2 saved to: {out_path} ✓")


# ============================================================
# DASHBOARD 3: PRODUCT INTELLIGENCE & RETURNS ANALYSIS
# ============================================================

def generate_dashboard3():
    logger.info("Generating Dashboard 3: Product Intelligence & Returns Analysis...")
    sales_path = PATHS["cleaned_sales_csv"]
    returns_path = PATHS["returns_csv"]
    sales = pd.read_csv(sales_path)
    returns = pd.read_csv(returns_path)

    fig = plt.figure(figsize=(16, 9), facecolor="#F8FAFC")
    fig.suptitle("PRODUCT PERFORMANCE, MARGIN PROTECTION & RETURNS AUDIT", fontsize=18, fontweight="bold", color="#0F172A", y=0.97)

    gs = fig.add_gridspec(3, 3, height_ratios=[0.25, 1, 1], hspace=0.35, wspace=0.25, left=0.06, right=0.95, top=0.91, bottom=0.06)

    # 1. KPI Cards Row
    kpi_ax = fig.add_subplot(gs[0, :])
    kpi_ax.axis("off")

    lost_val = abs(returns["line_revenue"].sum())
    gross_val = sales["line_revenue"].sum()
    loss_ratio = (lost_val / gross_val) * 100.0

    kpis = [
        ("TOTAL CANCELLATION LOSS", f"${lost_val:,.2f}", "#DC2626"),
        ("NON-SALE RECORDS", f"{len(returns):,} Rows", "#EA580C"),
        ("LOSS TO SALES RATIO", f"{loss_ratio:.2f}%", "#D97706"),
        ("FORMAL C-INVOICES", f"{returns['return_flag'].str.contains('C_invoice').sum():,}", "#6366F1"),
        ("TOTAL UNIQUE PRODUCTS", f"{sales['stock_code'].nunique():,} SKUs", "#0284C7"),
    ]

    for i, (title, val, color) in enumerate(kpis):
        x = i * 0.20 + 0.01
        rect = plt.Rectangle((x, 0.05), 0.18, 0.85, transform=kpi_ax.transAxes, facecolor="#FFFFFF", edgecolor="#E2E8F0", linewidth=1.2, zorder=2)
        kpi_ax.add_patch(rect)
        kpi_ax.text(x + 0.09, 0.65, title, transform=kpi_ax.transAxes, fontsize=9, fontweight="bold", color="#64748B", ha="center", va="center")
        kpi_ax.text(x + 0.09, 0.32, val, transform=kpi_ax.transAxes, fontsize=15, fontweight="bold", color=color, ha="center", va="center")

    # 2. Pareto 80/20 Cumulative Revenue Curve (Row 1, Cols 0-1)
    ax_pareto = fig.add_subplot(gs[1, :2])
    ax_pareto.set_facecolor("#FFFFFF")
    prod_rev = sales.groupby("stock_code")["line_revenue"].sum().sort_values(ascending=False)
    cum_pct = (prod_rev.cumsum() / prod_rev.sum()) * 100.0
    x_pct = (np.arange(1, len(prod_rev) + 1) / len(prod_rev)) * 100.0

    ax_pareto.plot(x_pct, cum_pct, color="#2563EB", linewidth=2.5, label="Cumulative Revenue (%)")
    ax_pareto.axhline(80, color="#DC2626", linestyle="--", linewidth=1.2, label="80% Revenue Threshold")
    ax_pareto.axvline(20, color="#059669", linestyle=":", linewidth=1.2, label="20% Product Threshold")
    ax_pareto.set_xlabel("% of Product Catalog (Ranked)", fontsize=9, fontweight="bold")
    ax_pareto.set_ylabel("Cumulative Revenue (%)", fontsize=9, fontweight="bold")
    ax_pareto.set_title("Pareto Principle: Cumulative Revenue vs Product Catalog Share", fontsize=11, fontweight="bold", pad=8, color="#1E293B")
    ax_pareto.legend(loc="lower right", fontsize=8.5)
    ax_pareto.grid(True, linestyle="--", alpha=0.3)

    # 3. Return Flag Breakdown (Row 1, Col 2)
    ax_flag = fig.add_subplot(gs[1, 2])
    ax_flag.set_facecolor("#FFFFFF")
    flag_counts = returns["return_flag"].value_counts()
    clean_labels = [f.replace("_", " ").title() for f in flag_counts.index]
    ax_flag.barh(clean_labels[::-1], flag_counts.values[::-1], color="#DC2626", alpha=0.85)
    ax_flag.set_xlabel("Record Count", fontsize=9, fontweight="bold")
    ax_flag.set_title("Non-Sale Category Breakdown", fontsize=11, fontweight="bold", pad=8, color="#1E293B")
    ax_flag.grid(axis="x", linestyle="--", alpha=0.3)

    # 4. Product Sales vs Return Exposure Quadrant Matrix (Row 2, Cols 0-1)
    ax_quad = fig.add_subplot(gs[2, :2])
    ax_quad.set_facecolor("#FFFFFF")

    # Aggregate sales and returns per stock_code
    psales = sales.groupby("stock_code").agg(sales_qty=("quantity", "sum"), sales_rev=("line_revenue", "sum"))
    prets = returns.groupby("stock_code").agg(ret_qty=("quantity", lambda x: abs(x.sum())))
    merged = psales.join(prets, how="inner")
    merged["return_rate"] = (merged["ret_qty"] / merged["sales_qty"]) * 100.0
    merged_filtered = merged[(merged["sales_qty"] >= 100) & (merged["return_rate"] <= 60)]

    ax_quad.scatter(merged_filtered["sales_qty"], merged_filtered["return_rate"], color="#0284C7", alpha=0.6, s=30, edgecolors="none")
    ax_quad.set_xscale("log")
    ax_quad.axhline(merged_filtered["return_rate"].median(), color="#EA580C", linestyle="--", linewidth=1.2, label=f"Median Return Rate: {merged_filtered['return_rate'].median():.1f}%")
    ax_quad.set_xlabel("Units Sold (Log Scale)", fontsize=9, fontweight="bold")
    ax_quad.set_ylabel("Return Rate (%)", fontsize=9, fontweight="bold")
    ax_quad.set_title("Product Matrix: Sales Volume vs Cancellation Exposure (Min 100 Units)", fontsize=11, fontweight="bold", pad=8, color="#1E293B")
    ax_quad.legend(loc="upper right", fontsize=8.5)
    ax_quad.grid(True, linestyle="--", alpha=0.3)

    # 5. Top Return Volume Products (Row 2, Col 2)
    ax_topret = fig.add_subplot(gs[2, 2])
    ax_topret.set_facecolor("#FFFFFF")
    top_ret_skus = returns.groupby("description")["quantity"].agg(lambda x: abs(x.sum())).sort_values(ascending=False).head(7)
    short_ret_names = [d[:18] + ".." if len(d) > 20 else d for d in top_ret_skus.index]
    ax_topret.barh(short_ret_names[::-1], top_ret_skus.values[::-1], color="#991B1B", alpha=0.85)
    ax_topret.set_xlabel("Units Returned", fontsize=9, fontweight="bold")
    ax_topret.set_title("Top Cancelled Products (Units)", fontsize=11, fontweight="bold", pad=8, color="#1E293B")
    ax_topret.grid(axis="x", linestyle="--", alpha=0.3)

    out_path = PATHS["screenshots_dir"] / "dashboard3_product_returns.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    logger.info(f"Dashboard 3 saved to: {out_path} ✓")


def main():
    logger.info("=" * 65)
    logger.info("STARTING AUTOMATED DASHBOARD VISUALS GENERATOR")
    logger.info("=" * 65)

    generate_dashboard1()
    generate_dashboard2()
    generate_dashboard3()

    logger.info("=" * 65)
    logger.info("ALL 3 DASHBOARD VISUALS GENERATED SUCCESSFULLY INTO screenshots/ ✓")
    logger.info("=" * 65)


if __name__ == "__main__":
    main()
