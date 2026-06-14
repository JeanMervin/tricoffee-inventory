from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from models import InventoryItem, InventoryCategory, StockTransaction
from datetime import datetime, timedelta
from sqlalchemy import func

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
@login_required
def index():
    if current_user.role != 'admin':
        return redirect(url_for('staff.dashboard'))

    all_items   = InventoryItem.query.all()
    in_stock    = [i for i in all_items if i.status == 'in_stock']
    low_stock   = [i for i in all_items if i.status == 'low_stock']
    out_stock   = [i for i in all_items if i.status == 'out_of_stock']
    categories  = InventoryCategory.query.all()

    recent_tx = (StockTransaction.query
                 .order_by(StockTransaction.transaction_date.desc())
                 .limit(12).all())

    today = datetime.utcnow().date()
    today_tx = (StockTransaction.query
                .filter(func.date(StockTransaction.transaction_date) == today)
                .count())

    # Category breakdown for bar chart
    cat_labels, cat_ok, cat_low, cat_out = [], [], [], []
    for cat in categories:
        items = InventoryItem.query.filter_by(category_id=cat.id).all()
        cat_labels.append(cat.name)
        cat_ok.append(len([i for i in items if i.status == 'in_stock']))
        cat_low.append(len([i for i in items if i.status == 'low_stock']))
        cat_out.append(len([i for i in items if i.status == 'out_of_stock']))

    # 7-day trend
    trend_labels, trend_in, trend_out, trend_transfer = [], [], [], []
    for d in range(6, -1, -1):
        day = datetime.utcnow() - timedelta(days=d)
        trend_labels.append(day.strftime('%b %d'))
        day_tx = StockTransaction.query.filter(
            func.date(StockTransaction.transaction_date) == day.date()
        ).all()
        trend_in.append(sum(t.quantity for t in day_tx if t.transaction_type == 'supplier_in'))
        trend_out.append(sum(t.quantity for t in day_tx if t.transaction_type == 'stock_out'))
        trend_transfer.append(sum(t.quantity for t in day_tx if t.transaction_type == 'transfer_to_area'))

    return render_template('dashboard.html',
        total_items   = len(all_items),
        in_stock      = in_stock,
        low_stock     = low_stock,
        out_stock     = out_stock,
        categories    = categories,
        recent_tx     = recent_tx,
        today_tx      = today_tx,
        cat_labels    = cat_labels,
        cat_ok        = cat_ok,
        cat_low       = cat_low,
        cat_out       = cat_out,
        trend_labels  = trend_labels,
        trend_in      = trend_in,
        trend_out     = trend_out,
        trend_transfer= trend_transfer,
    )
