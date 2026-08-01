from flask import Blueprint, render_template, redirect, url_for, session
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

    branch = session.get('admin_branch', 0)  # 0 = all branches

    q = InventoryItem.query
    if branch:
        q = q.filter_by(branch=branch)
    all_items = q.all()

    in_stock  = [i for i in all_items if i.status == 'in_stock']
    low_stock = [i for i in all_items if i.status == 'low_stock']
    out_stock = [i for i in all_items if i.status == 'out_of_stock']
    categories = InventoryCategory.query.all()

    tx_q = StockTransaction.query
    if branch:
        tx_q = tx_q.join(InventoryItem).filter(InventoryItem.branch == branch)
    recent_tx = tx_q.order_by(StockTransaction.transaction_date.desc()).limit(12).all()

    today = datetime.utcnow().date()
    today_tx = tx_q.filter(func.date(StockTransaction.transaction_date) == today).count()

    cat_labels, cat_ok, cat_low, cat_out = [], [], [], []
    for cat in categories:
        cq = InventoryItem.query.filter_by(category_id=cat.id)
        if branch:
            cq = cq.filter_by(branch=branch)
        items = cq.all()
        if not items:
            continue
        cat_labels.append(cat.name)
        cat_ok.append(len([i for i in items if i.status == 'in_stock']))
        cat_low.append(len([i for i in items if i.status == 'low_stock']))
        cat_out.append(len([i for i in items if i.status == 'out_of_stock']))

    trend_labels, trend_in, trend_out, trend_transfer = [], [], [], []
    for d in range(6, -1, -1):
        day = datetime.utcnow() - timedelta(days=d)
        trend_labels.append(day.strftime('%b %d'))
        day_q = StockTransaction.query
        if branch:
            day_q = day_q.join(InventoryItem).filter(InventoryItem.branch == branch)
        day_tx = day_q.filter(func.date(StockTransaction.transaction_date) == day.date()).all()
        trend_in.append(sum(t.quantity for t in day_tx if t.transaction_type == 'supplier_in'))
        trend_out.append(sum(t.quantity for t in day_tx if t.transaction_type == 'stock_out'))
        trend_transfer.append(sum(t.quantity for t in day_tx
            if t.transaction_type in ('transfer_to_area', 'borrow_main', 'borrow_b1_area')))

    branch_label = {0: 'All Branches', 1: 'Tricoffee 1', 2: 'Tricoffee 2'}.get(branch, 'Tricoffee')

    return render_template('dashboard.html',
        branch_label  = branch_label,
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
        admin_branch  = branch,
    )


@dashboard_bp.route('/set-branch/<int:branch>')
@login_required
def set_branch(branch):
    """Admin branch switcher — 0=all, 1=branch1, 2=branch2."""
    if current_user.role == 'admin':
        session['admin_branch'] = branch
    return redirect(url_for('dashboard.index'))
