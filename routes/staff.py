from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, InventoryItem, InventoryCategory, StockTransaction
from utils import log_action
from datetime import datetime
from sqlalchemy import func

staff_bp = Blueprint('staff', __name__)


# ── dashboard ─────────────────────────────────────────────────────────────────

@staff_bp.route('/dashboard')
@login_required
def dashboard():
    all_items  = InventoryItem.query.all()
    low_stock  = [i for i in all_items if i.status == 'low_stock']
    out_stock  = [i for i in all_items if i.status == 'out_of_stock']
    categories = InventoryCategory.query.all()

    recent_tx = (StockTransaction.query
                 .filter_by(user_id=current_user.id)
                 .order_by(StockTransaction.transaction_date.desc())
                 .limit(10).all())

    today = datetime.utcnow().date()
    morning_done = StockTransaction.query.filter(
        StockTransaction.transaction_type == 'count_open',
        func.date(StockTransaction.transaction_date) == today
    ).first() is not None

    eod_done = StockTransaction.query.filter(
        StockTransaction.transaction_type == 'stock_out',
        func.date(StockTransaction.transaction_date) == today
    ).first() is not None

    return render_template('staff/dashboard.html',
        total_items   = len(all_items),
        low_stock     = low_stock,
        out_stock     = out_stock,
        categories    = categories,
        recent_tx     = recent_tx,
        morning_done  = morning_done,
        eod_done      = eod_done,
        today         = today)


# ── morning weigh-in ──────────────────────────────────────────────────────────

@staff_bp.route('/morning-count', methods=['GET', 'POST'])
@login_required
def morning_count():
    """Opening weigh-in: staff sets area_storage_qty to physically-measured values."""
    today = datetime.utcnow().date()

    already_done = StockTransaction.query.filter(
        StockTransaction.transaction_type == 'count_open',
        func.date(StockTransaction.transaction_date) == today
    ).first()

    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    items      = InventoryItem.query.order_by(InventoryItem.name).all()

    if request.method == 'POST':
        force      = request.form.get('force_recount') == '1'
        if already_done and not force:
            flash('Morning count already submitted today. Tick "Force re-count" to override.', 'warning')
            return redirect(url_for('staff.morning_count'))

        saved = 0
        now   = datetime.utcnow()
        for key, raw in request.form.items():
            if not key.startswith('item_'):
                continue
            raw = raw.strip()
            if raw == '':
                continue
            try:
                item_id = int(key[5:])
                qty     = float(raw)
                if qty < 0:
                    continue
            except (ValueError, TypeError):
                continue

            item = InventoryItem.query.get(item_id)
            if not item:
                continue

            # ── Weigh-in is a RECORD only — does NOT change area_storage_qty.
            # The area cabinet (area_storage_qty) persists from day to day and
            # is only reduced by the end-of-day batch stock-out.
            db.session.add(StockTransaction(
                item_id          = item_id,
                transaction_type = 'count_open',
                quantity         = qty,
                remarks          = f'Daily weigh-in record.',
                user_id          = current_user.id,
                transaction_date = now,
            ))
            saved += 1

        log_action(current_user.id, 'Morning Count',
                   f'Weigh-in for {saved} items by {current_user.username}')
        db.session.commit()
        flash(f'Opening count saved for {saved} item(s). Have a great shift!', 'success')
        return redirect(url_for('staff.dashboard'))

    return render_template('staff/morning_count.html',
        categories   = categories,
        items        = items,
        already_done = already_done,
        today        = today)


# ── end-of-day batch stock-out ────────────────────────────────────────────────

@staff_bp.route('/batch-stockout', methods=['GET', 'POST'])
@login_required
def batch_stockout():
    """End-of-day: record all items consumed from area storage in one shot."""
    today      = datetime.utcnow().date()
    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    items      = InventoryItem.query.order_by(InventoryItem.name).all()

    if request.method == 'POST':
        saved   = 0
        skipped = []
        now     = datetime.utcnow()

        for key, raw in request.form.items():
            if not key.startswith('item_'):
                continue
            raw = raw.strip()
            if raw == '' or raw == '0':
                continue
            try:
                item_id = int(key[5:])
                qty     = float(raw)
                if qty <= 0:
                    continue
            except (ValueError, TypeError):
                continue

            item = InventoryItem.query.get(item_id)
            if not item:
                continue

            if item.area_storage_qty < qty:
                skipped.append(
                    f'{item.name}: requested {qty} but only {item.area_storage_qty} available'
                )
                continue

            item.area_storage_qty -= qty
            item.updated_at        = now
            db.session.add(StockTransaction(
                item_id          = item_id,
                transaction_type = 'stock_out',
                quantity         = qty,
                remarks          = f'EOD batch stock-out by {current_user.username}',
                user_id          = current_user.id,
                transaction_date = now,
            ))
            saved += 1

        for msg in skipped:
            flash(msg, 'warning')

        log_action(current_user.id, 'Batch Stock-Out (EOD)',
                   f'Stock-out for {saved} items by {current_user.username}')
        db.session.commit()

        if saved:
            flash(f'Stock-out recorded for {saved} item(s).', 'success')
            return redirect(url_for('reports.daily_summary'))
        else:
            flash('No items recorded — please enter at least one quantity.', 'danger')

    return render_template('staff/batch_stockout.html',
        categories = categories,
        items      = items,
        today      = today)



# ── bulk transfer: main → area ────────────────────────────────────────────────

@staff_bp.route('/bulk-transfer', methods=['GET', 'POST'])
@login_required
def bulk_transfer():
    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    items      = InventoryItem.query.order_by(InventoryItem.name).all()

    if request.method == 'POST':
        remarks = request.form.get('remarks', '').strip()
        saved, skipped = 0, []
        now = datetime.utcnow()

        for item in items:
            qty_raw = request.form.get(f'qty_{item.id}', '').strip()
            if not qty_raw:
                continue
            try:
                qty = float(qty_raw)
            except ValueError:
                continue
            if qty <= 0:
                continue
            if item.main_storage_qty < qty:
                skipped.append(f"{item.name}: only {item.main_storage_qty} in main storage")
                continue
            item.main_storage_qty -= qty
            item.area_storage_qty += qty
            item.updated_at = now
            db.session.add(StockTransaction(
                item_id=item.id, transaction_type="transfer_to_area",
                quantity=qty,
                remarks=remarks or f"Bulk transfer by {current_user.full_name or current_user.username}",
                user_id=current_user.id, transaction_date=now))
            log_action(current_user.id, "Bulk Transfer to Area",
                       f"+{qty} {item.storage_unit or item.unit_type} of {item.name}")
            saved += 1

        for msg in skipped:
            flash(msg, "warning")
        if saved:
            db.session.commit()
            flash(f"Transferred {saved} item(s) to area storage.", "success")
        else:
            flash("No quantities transferred.", "warning")
        return redirect(url_for("staff.bulk_transfer"))

    return render_template("staff/bulk_transfer.html", items=items, categories=categories)


# ── bulk stock-out from area ──────────────────────────────────────────────────

@staff_bp.route('/bulk-stockout-area', methods=['GET', 'POST'])
@login_required
def bulk_stockout_area():
    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    items      = InventoryItem.query.order_by(InventoryItem.name).all()

    if request.method == 'POST':
        remarks = request.form.get('remarks', '').strip()
        saved, skipped = 0, []
        now = datetime.utcnow()

        for item in items:
            qty_raw = request.form.get(f'qty_{item.id}', '').strip()
            if not qty_raw:
                continue
            try:
                qty = float(qty_raw)
            except ValueError:
                continue
            if qty <= 0:
                continue
            if item.area_storage_qty < qty:
                skipped.append(f"{item.name}: only {item.area_storage_qty} in area storage")
                continue
            item.area_storage_qty -= qty
            item.updated_at = now
            db.session.add(StockTransaction(
                item_id=item.id, transaction_type="stock_out",
                quantity=qty,
                remarks=remarks or f"Bulk stock-out by {current_user.full_name or current_user.username}",
                user_id=current_user.id, transaction_date=now))
            log_action(current_user.id, "Bulk Stock-Out (Area)",
                       f"-{qty} {item.storage_unit or item.unit_type} of {item.name}")
            saved += 1

        for msg in skipped:
            flash(msg, "warning")
        if saved:
            db.session.commit()
            flash(f"Stock-out recorded for {saved} item(s).", "success")
        else:
            flash("No quantities entered.", "warning")
        return redirect(url_for("staff.bulk_stockout_area"))

    return render_template("staff/bulk_stockout.html", items=items, categories=categories)

# ── existing single-item operations ──────────────────────────────────────────

@staff_bp.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    """Move stock from main storage → area storage."""
    categories = InventoryCategory.query.all()

    if request.method == 'POST':
        item_id = request.form.get('item_id', type=int)
        qty     = request.form.get('quantity', type=float)
        remarks = request.form.get('remarks', '')

        if not item_id or not qty or qty <= 0:
            flash('Select an item and enter a valid quantity.', 'danger')
            return redirect(url_for('staff.transfer'))

        item = InventoryItem.query.get_or_404(item_id)
        if item.main_storage_qty < qty:
            flash(f'Not enough in main storage. '
                  f'Available: {item.main_storage_qty} {item.unit_type}', 'warning')
            return redirect(url_for('staff.transfer'))

        item.main_storage_qty -= qty
        item.area_storage_qty += qty
        item.updated_at        = datetime.utcnow()
        db.session.add(StockTransaction(
            item_id=item_id, transaction_type='transfer_to_area',
            quantity=qty,
            remarks=remarks or f'Transferred by {current_user.full_name or current_user.username}',
            user_id=current_user.id, transaction_date=datetime.utcnow()))
        log_action(current_user.id, 'Transfer to Area',
                   f'{qty} {item.unit_type} of {item.name}')
        db.session.commit()
        flash(f'Transferred {qty} {item.unit_type} of "{item.name}" to area storage.', 'success')
        return redirect(url_for('staff.transfer'))

    items = InventoryItem.query.order_by(InventoryItem.name).all()
    return render_template('staff/transfer.html', items=items, categories=categories)


@staff_bp.route('/stock-out', methods=['GET', 'POST'])
@login_required
def stock_out():
    """Single-item stock-out from area storage."""
    categories = InventoryCategory.query.all()

    if request.method == 'POST':
        item_id = request.form.get('item_id', type=int)
        qty     = request.form.get('quantity', type=float)
        remarks = request.form.get('remarks', '')

        if not item_id or not qty or qty <= 0:
            flash('Select an item and enter a valid quantity.', 'danger')
            return redirect(url_for('staff.stock_out'))

        item = InventoryItem.query.get_or_404(item_id)
        if item.area_storage_qty < qty:
            flash(f'Not enough in area storage. '
                  f'Available: {item.area_storage_qty} {item.unit_type}', 'warning')
            return redirect(url_for('staff.stock_out'))

        item.area_storage_qty -= qty
        item.updated_at        = datetime.utcnow()
        db.session.add(StockTransaction(
            item_id=item_id, transaction_type='stock_out',
            quantity=qty,
            remarks=remarks or f'Used by {current_user.full_name or current_user.username}',
            user_id=current_user.id, transaction_date=datetime.utcnow()))
        log_action(current_user.id, 'Stock Out',
                   f'{qty} {item.unit_type} of {item.name} used from area')
        db.session.commit()
        flash(f'Marked {qty} {item.unit_type} of "{item.name}" as used.', 'success')
        return redirect(url_for('staff.stock_out'))

    items = InventoryItem.query.order_by(InventoryItem.name).all()
    return render_template('staff/stock_out.html', items=items, categories=categories)


@staff_bp.route('/my-transactions')
@login_required
def my_transactions():
    page = request.args.get('page', 1, type=int)
    txs  = (StockTransaction.query
            .filter_by(user_id=current_user.id)
            .order_by(StockTransaction.transaction_date.desc())
            .paginate(page=page, per_page=20, error_out=False))
    return render_template('staff/my_transactions.html', transactions=txs)
