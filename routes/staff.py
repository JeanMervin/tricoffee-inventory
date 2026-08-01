from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, InventoryItem, InventoryCategory, StockTransaction
from utils import log_action
from datetime import datetime
from sqlalchemy import func

staff_bp = Blueprint('staff', __name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _my_items():
    return InventoryItem.query.filter_by(branch=current_user.branch).order_by(InventoryItem.name)


def _check_item(item_id):
    """Get item only if it belongs to current user's branch."""
    item = db.session.get(InventoryItem, item_id)
    if not item or item.branch != current_user.branch:
        return None
    return item


# ── dashboard ─────────────────────────────────────────────────────────────────

@staff_bp.route('/dashboard')
@login_required
def dashboard():
    all_items = _my_items().all()
    today     = datetime.utcnow().date()

    recent_tx = (StockTransaction.query
                 .filter_by(user_id=current_user.id)
                 .order_by(StockTransaction.transaction_date.desc())
                 .limit(10).all())

    morning_done = StockTransaction.query.join(InventoryItem).filter(
        StockTransaction.transaction_type == 'count_open',
        StockTransaction.user_id == current_user.id,
        InventoryItem.branch == current_user.branch,
        func.date(StockTransaction.transaction_date) == today
    ).first() is not None

    eod_done = StockTransaction.query.join(InventoryItem).filter(
        StockTransaction.transaction_type == 'stock_out',
        StockTransaction.user_id == current_user.id,
        InventoryItem.branch == current_user.branch,
        func.date(StockTransaction.transaction_date) == today
    ).first() is not None

    return render_template('staff/dashboard.html',
        total_items  = len(all_items),
        low_stock    = [i for i in all_items if i.status == 'low_stock'],
        out_stock    = [i for i in all_items if i.status == 'out_of_stock'],
        categories   = InventoryCategory.query.all(),
        recent_tx    = recent_tx,
        morning_done = morning_done,
        eod_done     = eod_done,
        today        = today)


# ── opening weigh-in ──────────────────────────────────────────────────────────

@staff_bp.route('/morning-count', methods=['GET', 'POST'])
@login_required
def morning_count():
    today = datetime.utcnow().date()

    already_done = StockTransaction.query.join(InventoryItem).filter(
        StockTransaction.transaction_type == 'count_open',
        StockTransaction.user_id == current_user.id,
        InventoryItem.branch == current_user.branch,
        func.date(StockTransaction.transaction_date) == today
    ).first()

    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    items      = _my_items().all()

    if request.method == 'POST':
        force = request.form.get('force_recount') == '1'
        if already_done and not force:
            flash('Opening count already submitted today. Tick "Re-submit" to override.', 'warning')
            return redirect(url_for('staff.morning_count'))

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
                   f'Weigh-in for {saved} items — {current_user.username} (Branch {current_user.branch})')
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
                   f'Stock-out for {saved} items — Branch {current_user.branch}')
        db.session.commit()

        if saved:
            flash(f'Stock-out recorded for {saved} item(s).', 'success')
            return redirect(url_for('staff.dashboard'))
        else:
            flash('No items recorded.', 'danger')

    return render_template('staff/batch_stockout.html',
        categories=categories, items=items, today=today)


# ── bulk transfer: shared main storage → own area (BRANCH 1 ONLY) ─────────────
#
# Tricoffee 1 is the branch that physically receives supplier deliveries, so
# its main_storage_qty is the single source of truth for the shared pool.
# Tricoffee 2 no longer uses this page — they use Borrow instead, which lets
# them explicitly choose to draw from this same shared pool OR from
# Tricoffee 1's area storage cabinet.

@staff_bp.route('/bulk-transfer', methods=['GET', 'POST'])
@login_required
def bulk_transfer():
    if current_user.branch != 1:
        flash('Tricoffee 2 uses Borrow to get stock — from Main Storage or Tricoffee 1 Area.', 'info')
        return redirect(url_for('staff.borrow'))

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
                item_id=item.id, transaction_type='transfer_to_area', quantity=qty,
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

    return render_template('staff/bulk_transfer.html', items=items, categories=categories,
        source_main_qty={item.id: item.main_storage_qty for item in items})


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
                item_id=item.id, transaction_type='stock_out', quantity=qty,
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


# ── borrow (Tricoffee 2 only): choose Main Storage OR Tricoffee 1 Area ────────
#
# This is Tricoffee 2's ONLY way to bring stock into their area storage.
# Two sources:
#   'main'    — the shared main-storage pool. The real quantity lives on the
#               matching Branch 1 item (by name); Branch 2 has no main storage
#               of its own for shared items.
#   'b1_area' — Tricoffee 1's area/counter cabinet, for items (Bruna, Oatside,
#               Condensed Milk, Everwhip, etc.) that go straight there from
#               the supplier and never pass through main storage at all.

@staff_bp.route('/borrow', methods=['GET', 'POST'])
@login_required
def borrow():
    if current_user.branch != 2:
        flash('Borrow is only available for Tricoffee 2. Use Stock-In instead.', 'warning')
        return redirect(url_for('staff.dashboard'))

    categories = InventoryCategory.query.order_by(InventoryCategory.name).all()
    my_items   = _my_items().all()
    b1_items   = InventoryItem.query.filter_by(branch=1).order_by(InventoryItem.name).all()
    b1_by_name = {i.name.lower(): i for i in b1_items}

    # For the "Main Storage" tab: map each of my items to the Branch 1 row
    # that actually holds the shared main_storage_qty for that item name.
    main_sources = {item.id: b1_by_name.get(item.name.lower(), item) for item in my_items}

    if request.method == 'POST':
        source         = request.form.get('source', 'main')  # 'main' | 'b1_area'
        remarks        = request.form.get('remarks', '').strip()
        saved, skipped = 0, []
        now            = datetime.utcnow()

        if source == 'main':
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

                main_source = main_sources[item.id]
                if main_source.main_storage_qty < qty:
                    skipped.append(f'{item.name}: only {main_source.main_storage_qty} in main storage')
                    continue

                main_source.main_storage_qty -= qty
                main_source.updated_at = now
                item.area_storage_qty += qty
                item.updated_at = now

                if main_source.id == item.id:
                    db.session.add(StockTransaction(
                        item_id=item.id, transaction_type='transfer_to_area', quantity=qty,
                        remarks=remarks or f'Transfer by {current_user.username}',
                        user_id=current_user.id, transaction_date=now))
                else:
                    db.session.add(StockTransaction(
                        item_id=main_source.id, transaction_type='main_lent_to_b2', quantity=qty,
                        remarks=remarks or f'Drawn by Tricoffee 2 ({current_user.username})',
                        user_id=current_user.id, transaction_date=now))
                    db.session.add(StockTransaction(
                        item_id=item.id, transaction_type='borrow_main', quantity=qty,
                        remarks=remarks or 'From shared main storage',
                        user_id=current_user.id, transaction_date=now))
                log_action(current_user.id, 'Stock-In (Shared Main)',
                           f'+{qty} {item.storage_unit or "pcs"} of {item.name}')
                saved += 1

        else:  # b1_area
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

                b2_item = next((i for i in my_items if i.name.lower() == b1_item.name.lower()), None)
                if not b2_item:
                    skipped.append(f'{b1_item.name}: no matching item in Tricoffee 2')
                    continue

                b1_item.area_storage_qty -= qty
                b1_item.updated_at = now
                db.session.add(StockTransaction(
                    item_id=b1_item.id, transaction_type='lent_to_b2', quantity=qty,
                    remarks=remarks or f'Lent to T2 by {current_user.username}',
                    user_id=current_user.id, transaction_date=now))

                b2_item.area_storage_qty += qty
                b2_item.updated_at = now
                db.session.add(StockTransaction(
                    item_id=b2_item.id, transaction_type='borrow_b1_area', quantity=qty,
                    remarks=remarks or f'Borrowed from T1 area by {current_user.username}',
                    user_id=current_user.id, transaction_date=now))

                log_action(current_user.id, 'Borrow from T1 Area',
                           f'+{qty} {b2_item.storage_unit or "pcs"} of {b2_item.name}')
                saved += 1

        for msg in skipped:
            flash(msg, 'warning')
        if saved:
            db.session.commit()
            flash(f'Received {saved} item(s) into your area storage.', 'success')
        else:
            flash('No quantities entered.', 'warning')
        return redirect(url_for('staff.borrow'))

    return render_template('staff/borrow.html',
        my_items=my_items, b1_items=b1_items, categories=categories,
        main_source_qty={item.id: main_sources[item.id].main_storage_qty for item in my_items})


# ── single-item operations ────────────────────────────────────────────────────

@staff_bp.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    if current_user.branch != 1:
        return redirect(url_for('staff.borrow'))

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

    return render_template('staff/transfer.html',
        items=_my_items().all(), categories=categories)


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

    return render_template('staff/stock_out.html',
        items=_my_items().all(), categories=categories)


@staff_bp.route('/my-transactions')
@login_required
def my_transactions():
    page = request.args.get('page', 1, type=int)
    txs  = (StockTransaction.query
            .filter_by(user_id=current_user.id)
            .order_by(StockTransaction.transaction_date.desc())
            .paginate(page=page, per_page=20, error_out=False))
    return render_template('staff/my_transactions.html', transactions=txs)
