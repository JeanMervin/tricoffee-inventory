from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, InventoryItem, InventoryCategory, StockTransaction
from utils import log_action
from datetime import datetime
from sqlalchemy import func

staff_bp = Blueprint('staff', __name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _my_items():
    """Items belonging to the current user's branch."""
    return InventoryItem.query.filter_by(branch=current_user.branch).order_by(InventoryItem.name)


def _check_item(item_id):
    """Get item and verify it belongs to current user's branch."""
    item = db.session.get(InventoryItem, item_id)
    if not item or item.branch != current_user.branch:
        return None
    return item


# ── dashboard ─────────────────────────────────────────────────────────────────

@staff_bp.route('/dashboard')
@login_required
def dashboard():
    all_items = _my_items().all()
    low_stock = [i for i in all_items if i.status == 'low_stock']
    out_stock = [i for i in all_items if i.status == 'out_of_stock']

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
        total_items  = len(all_items),
        low_stock    = low_stock,
        out_stock    = out_stock,
        categories   = InventoryCategory.query.all(),
        recent_tx    = recent_tx,
        morning_done = morning_done,
        eod_done     = eod_done,
        today        = today)


# ── opening weigh-in ──────────────────────────────────────────────────────────

@staff_bp.route('/morning-count', methods=['GET', 'POST'])
@login_required
def morning_count():
    today      = datetime.utcnow().date()
    already_done = StockTransaction.query.filter(
        StockTransaction.transaction_type == 'count_open',
        StockTransaction.user_id == current_user.id,
        func.date(StockTransaction.transaction_date) == today
    ).first()

    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    items      = _my_items().all()

    if request.method == 'POST':
        saved, now = 0, datetime.utcnow()
        for key, raw in request.form.items():
            if not key.startswith('item_'):
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                item_id = int(key[5:])
                qty     = float(raw)
                if qty < 0:
                    continue
            except (ValueError, TypeError):
                continue

            item = _check_item(item_id)
            if not item:
                continue

            db.session.add(StockTransaction(
                item_id=item_id, transaction_type='count_open',
                quantity=qty, remarks='Daily weigh-in record.',
                user_id=current_user.id, transaction_date=now))
            saved += 1

        log_action(current_user.id, 'Opening Count',
                   f'Weigh-in for {saved} items by {current_user.username}')
        db.session.commit()
        flash(f'Opening count saved for {saved} item(s).', 'success')
        return redirect(url_for('staff.dashboard'))

    return render_template('staff/morning_count.html',
        categories=categories, items=items,
        already_done=already_done, today=today)


# ── end-of-day batch stock-out ────────────────────────────────────────────────

@staff_bp.route('/batch-stockout', methods=['GET', 'POST'])
@login_required
def batch_stockout():
    today      = datetime.utcnow().date()
    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    items      = _my_items().all()

    if request.method == 'POST':
        saved, skipped, now = 0, [], datetime.utcnow()
        for key, raw in request.form.items():
            if not key.startswith('item_'):
                continue
            raw = raw.strip()
            if not raw or raw == '0':
                continue
            try:
                item_id = int(key[5:])
                qty     = float(raw)
                if qty <= 0:
                    continue
            except (ValueError, TypeError):
                continue

            item = _check_item(item_id)
            if not item:
                continue
            if item.area_storage_qty < qty:
                skipped.append(f'{item.name}: only {item.area_storage_qty} available')
                continue

            item.area_storage_qty -= qty
            item.updated_at = now
            db.session.add(StockTransaction(
                item_id=item_id, transaction_type='stock_out',
                quantity=qty, remarks=f'EOD stock-out by {current_user.username}',
                user_id=current_user.id, transaction_date=now))
            saved += 1

        for msg in skipped:
            flash(msg, 'warning')
        log_action(current_user.id, 'Batch Stock-Out (EOD)',
                   f'Stock-out for {saved} items')
        db.session.commit()

        if saved:
            flash(f'Stock-out recorded for {saved} item(s).', 'success')
            return redirect(url_for('staff.dashboard'))
        else:
            flash('No items recorded.', 'danger')

    return render_template('staff/batch_stockout.html',
        categories=categories, items=items, today=today)


# ── bulk transfer: main → own area (both branches) ────────────────────────────

@staff_bp.route('/bulk-transfer', methods=['GET', 'POST'])
@login_required
def bulk_transfer():
    """Move stock from shared main storage into this branch's area storage."""
    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    items      = _my_items().all()

    if request.method == 'POST':
        remarks        = request.form.get('remarks', '').strip()
        saved, skipped = 0, []
        now            = datetime.utcnow()
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
                skipped.append(f'{item.name}: only {item.main_storage_qty} in main storage')
                continue
            item.main_storage_qty -= qty
            item.area_storage_qty += qty
            item.updated_at = now
            db.session.add(StockTransaction(
                item_id=item.id, transaction_type='transfer_to_area',
                quantity=qty,
                remarks=remarks or f'Transfer by {current_user.full_name or current_user.username}',
                user_id=current_user.id, transaction_date=now))
            log_action(current_user.id, 'Transfer to Area',
                       f'+{qty} {item.storage_unit or "pcs"} of {item.name}')
            saved += 1

        for msg in skipped:
            flash(msg, 'warning')
        if saved:
            db.session.commit()
            flash(f'Transferred {saved} item(s) to area storage.', 'success')
        else:
            flash('No quantities transferred.', 'warning')
        return redirect(url_for('staff.bulk_transfer'))

    return render_template('staff/bulk_transfer.html', items=items, categories=categories)


# ── bulk stock-out from area ──────────────────────────────────────────────────

@staff_bp.route('/bulk-stockout-area', methods=['GET', 'POST'])
@login_required
def bulk_stockout_area():
    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    items      = _my_items().all()

    if request.method == 'POST':
        remarks        = request.form.get('remarks', '').strip()
        saved, skipped = 0, []
        now            = datetime.utcnow()
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
                skipped.append(f'{item.name}: only {item.area_storage_qty} in area storage')
                continue
            item.area_storage_qty -= qty
            item.updated_at = now
            db.session.add(StockTransaction(
                item_id=item.id, transaction_type='stock_out',
                quantity=qty,
                remarks=remarks or f'Bulk stock-out by {current_user.full_name or current_user.username}',
                user_id=current_user.id, transaction_date=now))
            log_action(current_user.id, 'Bulk Stock-Out',
                       f'-{qty} {item.storage_unit or "pcs"} of {item.name}')
            saved += 1

        for msg in skipped:
            flash(msg, 'warning')
        if saved:
            db.session.commit()
            flash(f'Stock-out recorded for {saved} item(s).', 'success')
        else:
            flash('No quantities entered.', 'warning')
        return redirect(url_for('staff.bulk_stockout_area'))

    return render_template('staff/bulk_stockout.html', items=items, categories=categories)


# ── cross-branch borrow (Tricoffee 2 only) ────────────────────────────────────

@staff_bp.route('/borrow', methods=['GET', 'POST'])
@login_required
def borrow():
    """
    Tricoffee 2 can borrow stock from:
      - Shared main storage (main_storage_qty on any item)
      - Tricoffee 1's area storage (area_storage_qty on branch=1 items)

    The matching branch-2 item's area_storage_qty is increased.
    The source quantity is deducted and logged on both sides.
    """
    if current_user.branch != 2:
        flash('This page is only available for Tricoffee 2.', 'warning')
        return redirect(url_for('staff.dashboard'))

    categories  = InventoryCategory.query.order_by(InventoryCategory.name).all()
    my_items    = _my_items().all()

    # Build a lookup: name → branch-2 item
    b2_by_name  = {i.name.lower(): i for i in my_items}

    # Branch-1 items that have stock in area storage
    b1_items    = (InventoryItem.query.filter_by(branch=1)
                   .order_by(InventoryItem.name).all())

    if request.method == 'POST':
        source  = request.form.get('source', 'main')  # 'main' | 'b1_area'
        remarks = request.form.get('remarks', '').strip()
        saved, skipped = 0, []
        now = datetime.utcnow()

        if source == 'main':
            # Borrow from shared main storage → my area storage
            for item in my_items:
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
                    skipped.append(f'{item.name}: only {item.main_storage_qty} in main storage')
                    continue

                item.main_storage_qty -= qty
                item.area_storage_qty += qty
                item.updated_at = now
                db.session.add(StockTransaction(
                    item_id=item.id, transaction_type='borrow_main',
                    quantity=qty,
                    remarks=remarks or f'Borrowed from main by {current_user.username}',
                    user_id=current_user.id, transaction_date=now))
                log_action(current_user.id, 'Borrow from Main',
                           f'+{qty} {item.storage_unit or "pcs"} of {item.name} → T2 area')
                saved += 1

        else:
            # Borrow from Tricoffee 1 area → Tricoffee 2 area
            for b1_item in b1_items:
                qty_raw = request.form.get(f'b1_{b1_item.id}', '').strip()
                if not qty_raw:
                    continue
                try:
                    qty = float(qty_raw)
                except ValueError:
                    continue
                if qty <= 0:
                    continue
                if b1_item.area_storage_qty < qty:
                    skipped.append(f'{b1_item.name}: T1 only has {b1_item.area_storage_qty}')
                    continue

                # Find matching branch-2 item by name
                b2_item = b2_by_name.get(b1_item.name.lower())
                if not b2_item:
                    skipped.append(f'{b1_item.name}: no matching item in Tricoffee 2')
                    continue

                # Deduct from T1 area
                b1_item.area_storage_qty -= qty
                b1_item.updated_at = now
                db.session.add(StockTransaction(
                    item_id=b1_item.id, transaction_type='lent_to_b2',
                    quantity=qty,
                    remarks=remarks or f'Lent to T2 by {current_user.username}',
                    user_id=current_user.id, transaction_date=now))

                # Add to T2 area
                b2_item.area_storage_qty += qty
                b2_item.updated_at = now
                db.session.add(StockTransaction(
                    item_id=b2_item.id, transaction_type='borrow_b1_area',
                    quantity=qty,
                    remarks=remarks or f'Borrowed from T1 area by {current_user.username}',
                    user_id=current_user.id, transaction_date=now))

                log_action(current_user.id, 'Borrow from T1 Area',
                           f'+{qty} {b2_item.storage_unit or "pcs"} of {b2_item.name}')
                saved += 1

        for msg in skipped:
            flash(msg, 'warning')
        if saved:
            db.session.commit()
            flash(f'Borrowed {saved} item(s) successfully.', 'success')
        else:
            flash('No quantities entered.', 'warning')
        return redirect(url_for('staff.borrow'))

    return render_template('staff/borrow.html',
        my_items=my_items, b1_items=b1_items,
        categories=categories)


# ── single item operations ────────────────────────────────────────────────────

@staff_bp.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    categories = InventoryCategory.query.all()
    if request.method == 'POST':
        item_id = request.form.get('item_id', type=int)
        qty     = request.form.get('quantity', type=float)
        remarks = request.form.get('remarks', '')

        if not item_id or not qty or qty <= 0:
            flash('Select an item and enter a valid quantity.', 'danger')
            return redirect(url_for('staff.transfer'))

        item = _check_item(item_id)
        if not item:
            flash('Item not found.', 'danger')
            return redirect(url_for('staff.transfer'))
        if item.main_storage_qty < qty:
            flash(f'Not enough in main storage. Available: {item.main_storage_qty}', 'warning')
            return redirect(url_for('staff.transfer'))

        item.main_storage_qty -= qty
        item.area_storage_qty += qty
        item.updated_at = datetime.utcnow()
        db.session.add(StockTransaction(
            item_id=item_id, transaction_type='transfer_to_area', quantity=qty,
            remarks=remarks or f'Transfer by {current_user.full_name or current_user.username}',
            user_id=current_user.id, transaction_date=datetime.utcnow()))
        log_action(current_user.id, 'Transfer to Area',
                   f'{qty} {item.storage_unit or "pcs"} of {item.name}')
        db.session.commit()
        flash(f'Transferred {qty} of "{item.name}" to area storage.', 'success')
        return redirect(url_for('staff.transfer'))

    items = _my_items().all()
    return render_template('staff/transfer.html', items=items, categories=categories)


@staff_bp.route('/stock-out', methods=['GET', 'POST'])
@login_required
def stock_out():
    categories = InventoryCategory.query.all()
    if request.method == 'POST':
        item_id = request.form.get('item_id', type=int)
        qty     = request.form.get('quantity', type=float)
        remarks = request.form.get('remarks', '')

        if not item_id or not qty or qty <= 0:
            flash('Select an item and enter a valid quantity.', 'danger')
            return redirect(url_for('staff.stock_out'))

        item = _check_item(item_id)
        if not item:
            flash('Item not found.', 'danger')
            return redirect(url_for('staff.stock_out'))
        if item.area_storage_qty < qty:
            flash(f'Not enough in area storage. Available: {item.area_storage_qty}', 'warning')
            return redirect(url_for('staff.stock_out'))

        item.area_storage_qty -= qty
        item.updated_at = datetime.utcnow()
        db.session.add(StockTransaction(
            item_id=item_id, transaction_type='stock_out', quantity=qty,
            remarks=remarks or f'Used by {current_user.full_name or current_user.username}',
            user_id=current_user.id, transaction_date=datetime.utcnow()))
        log_action(current_user.id, 'Stock Out',
                   f'{qty} {item.storage_unit or "pcs"} of {item.name}')
        db.session.commit()
        flash(f'Marked {qty} of "{item.name}" as used.', 'success')
        return redirect(url_for('staff.stock_out'))

    items = _my_items().all()
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
