from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import login_required, current_user
from models import db, InventoryItem, InventoryCategory, StockTransaction
from utils import admin_required, log_action
from datetime import datetime

inventory_bp = Blueprint('inventory', __name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _branch_filter(query):
    """Filter by branch: staff sees their branch, admin sees selected or all."""
    if current_user.role == 'admin':
        branch = session.get('admin_branch', 0)
        if branch:
            return query.filter_by(branch=branch)
        return query
    return query.filter_by(branch=current_user.branch)


def _paginate(query, per_page=20):
    page = request.args.get('page', 1, type=int)
    return query.paginate(page=page, per_page=per_page, error_out=False)


class _SimplePagination:
    """Minimal drop-in replacement for Flask-SQLAlchemy's Pagination, for plain lists."""
    def __init__(self, items_list, page, per_page):
        self.page      = page
        self.per_page  = per_page
        total          = len(items_list)
        self.total     = total
        self.pages     = max(1, (total + per_page - 1) // per_page)
        start          = (page - 1) * per_page
        self.items     = items_list[start:start + per_page]
        self.has_prev  = page > 1
        self.has_next  = page < self.pages
        self.prev_num  = page - 1 if self.has_prev else None
        self.next_num  = page + 1 if self.has_next else None

    def iter_pages(self):
        return range(1, self.pages + 1)


def _manual_paginate(items_list, per_page=20):
    page = request.args.get('page', 1, type=int)
    return _SimplePagination(items_list, page, per_page)


# ── list views ────────────────────────────────────────────────────────────────

@inventory_bp.route('/')
@login_required
@admin_required
def list_all():
    search   = request.args.get('search', '')
    cat_id   = request.args.get('category_id', '')
    status_f = request.args.get('status', '')
    sort     = request.args.get('sort', 'name')

    q = _branch_filter(InventoryItem.query)
    if search:  q = q.filter(InventoryItem.name.ilike(f'%{search}%'))
    if cat_id:  q = q.filter_by(category_id=cat_id)
    if sort == 'stock_asc':    q = q.order_by(InventoryItem.area_storage_qty.asc())
    elif sort == 'stock_desc': q = q.order_by(InventoryItem.area_storage_qty.desc())
    else:                      q = q.order_by(InventoryItem.name.asc())

    all_rows = q.all()
    if status_f:
        all_rows = [i for i in all_rows if i.status == status_f]

    categories = InventoryCategory.query.all()
    return render_template('inventory/list.html',
        items=_paginate(q), categories=categories, all_rows=all_rows,
        search=search, selected_category=cat_id,
        selected_status=status_f, sort=sort, current_category=None)


@inventory_bp.route('/category/<slug>')
@login_required
@admin_required
def list_by_category(slug):
    category = InventoryCategory.query.filter_by(slug=slug).first_or_404()
    search   = request.args.get('search', '')
    sort     = request.args.get('sort', 'name')

    q = _branch_filter(InventoryItem.query).filter_by(category_id=category.id)
    if search: q = q.filter(InventoryItem.name.ilike(f'%{search}%'))
    if sort == 'stock_asc':    q = q.order_by(InventoryItem.area_storage_qty.asc())
    elif sort == 'stock_desc': q = q.order_by(InventoryItem.area_storage_qty.desc())
    else:                      q = q.order_by(InventoryItem.name.asc())

    categories = InventoryCategory.query.all()
    return render_template('inventory/list.html',
        items=_paginate(q), categories=categories, all_rows=q.all(),
        search=search, selected_category=str(category.id),
        selected_status='', sort=sort, current_category=category)


# ── CRUD ──────────────────────────────────────────────────────────────────────

@inventory_bp.route('/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_item():
    categories = InventoryCategory.query.all()
    if request.method == 'POST':
        name         = request.form.get('name', '').strip()
        cat_id       = request.form.get('category_id')
        unit_type    = request.form.get('unit_type', 'g/ml')
        storage_unit = request.form.get('storage_unit', 'pcs')
        min_stk      = request.form.get('minimum_stock', 10, type=float)
        branch       = request.form.get('branch', 1, type=int)

        if not name or not cat_id:
            flash('Name and category are required.', 'danger')
        elif InventoryItem.query.filter_by(name=name, category_id=cat_id, branch=branch).first():
            flash('An item with that name already exists in this category for this branch.', 'danger')
        else:
            item = InventoryItem(
                name=name, branch=branch, category_id=int(cat_id),
                unit_type=unit_type, storage_unit=storage_unit,
                main_storage_qty=0, area_storage_qty=0, minimum_stock=min_stk,
                created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            db.session.add(item)
            log_action(current_user.id, 'Add Item', f'Added: {name} (branch {branch})')
            db.session.commit()
            flash(f'Item "{name}" added to Branch {branch}.', 'success')
            return redirect(url_for('inventory.list_all'))

    return render_template('inventory/add.html', categories=categories)


@inventory_bp.route('/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_item(item_id):
    item       = InventoryItem.query.get_or_404(item_id)
    categories = InventoryCategory.query.all()
    if request.method == 'POST':
        item.name          = request.form.get('name', item.name).strip()
        item.category_id   = request.form.get('category_id', item.category_id, type=int)
        item.unit_type     = request.form.get('unit_type', item.unit_type)
        item.storage_unit  = request.form.get('storage_unit', item.storage_unit or 'pcs')
        item.branch        = request.form.get('branch', item.branch, type=int)
        item.minimum_stock = request.form.get('minimum_stock', item.minimum_stock, type=float)
        item.updated_at    = datetime.utcnow()
        log_action(current_user.id, 'Edit Item', f'Edited: {item.name} (branch {item.branch})')
        db.session.commit()
        flash(f'Item "{item.name}" updated.', 'success')
        return redirect(url_for('inventory.list_all'))
    return render_template('inventory/edit.html', item=item, categories=categories)


@inventory_bp.route('/delete/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def delete_item(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    name = item.name
    log_action(current_user.id, 'Delete Item', f'Deleted: {name}')
    db.session.delete(item)
    db.session.commit()
    flash(f'Item "{name}" deleted.', 'success')
    return redirect(url_for('inventory.list_all'))


# ── stock-in from supplier → main storage (shared, bulk) ─────────────────────

def _shared_main_items():
    """
    One row per logical item name — the true shared main-storage pool.
    Prefers the Branch 1 row (since it's the branch that receives deliveries
    directly); falls back to Branch 2's row for items exclusive to Branch 2
    (e.g. Buldak, Noodles) that have no Branch 1 counterpart.
    """
    all_items = InventoryItem.query.order_by(InventoryItem.branch.asc(), InventoryItem.name).all()
    seen = {}
    for item in all_items:
        key = item.name.lower()
        if key not in seen:
            seen[key] = item
    return sorted(seen.values(), key=lambda i: i.name)


@inventory_bp.route('/stock-in', methods=['GET', 'POST'])
@login_required
@admin_required
def stock_in():
    """Bulk stock-in from supplier into the shared main storage."""
    categories = InventoryCategory.query.all()
    items = _shared_main_items()

    if request.method == 'POST':
        remarks = request.form.get('remarks', '').strip()
        saved, now = 0, datetime.utcnow()
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
            item.main_storage_qty += qty
            item.updated_at = now
            db.session.add(StockTransaction(
                item_id=item.id, transaction_type='supplier_in',
                quantity=qty, remarks=remarks or 'Supplier delivery',
                user_id=current_user.id, transaction_date=now))
            log_action(current_user.id, 'Stock In (Supplier)',
                       f'+{qty} {item.storage_unit or "pcs"} of {item.name} → main storage')
            saved += 1
        if saved:
            db.session.commit()
            flash(f'Stock updated for {saved} item(s) in main storage.', 'success')
        else:
            flash('No quantities entered.', 'warning')
        return redirect(url_for('inventory.stock_in'))

    return render_template('inventory/stock_in.html', items=items, categories=categories)


# ── adjustment ────────────────────────────────────────────────────────────────

@inventory_bp.route('/adjustment/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def adjustment(item_id):
    item         = InventoryItem.query.get_or_404(item_id)
    storage_type = request.form.get('storage_type', 'area')
    qty          = request.form.get('quantity', type=float)
    remarks      = request.form.get('remarks', 'Manual adjustment')

    if qty is None or qty < 0:
        flash('Invalid quantity.', 'danger')
        return redirect(url_for('inventory.list_all'))

    if storage_type == 'main':
        item.main_storage_qty = qty
        ttype = 'adjustment_main'
    else:
        item.area_storage_qty = qty
        ttype = 'adjustment_area'

    item.updated_at = datetime.utcnow()
    db.session.add(StockTransaction(
        item_id=item_id, transaction_type=ttype, quantity=qty,
        remarks=remarks, user_id=current_user.id,
        transaction_date=datetime.utcnow()))
    log_action(current_user.id, 'Adjustment',
               f'{storage_type} of {item.name} set to {qty} {item.storage_unit or "pcs"}')
    db.session.commit()
    flash(f'Adjustment saved for "{item.name}".', 'success')
    return redirect(url_for('inventory.list_all'))


# ── transactions ──────────────────────────────────────────────────────────────

@inventory_bp.route('/transactions')
@login_required
@admin_required
def transactions():
    item_id = request.args.get('item_id', '')
    ttype   = request.args.get('type', '')
    q = StockTransaction.query.join(InventoryItem)
    branch = session.get('admin_branch', 0)
    if branch:
        q = q.filter(InventoryItem.branch == branch)
    if item_id: q = q.filter(StockTransaction.item_id == item_id)
    if ttype:   q = q.filter(StockTransaction.transaction_type == ttype)
    txs   = _paginate(q.order_by(StockTransaction.transaction_date.desc()), per_page=25)
    items = _branch_filter(InventoryItem.query).order_by(InventoryItem.name).all()
    return render_template('inventory/transactions.html',
        transactions=txs, items=items,
        selected_item=item_id, selected_type=ttype)


@inventory_bp.route('/transactions/delete/<int:tx_id>', methods=['POST'])
@login_required
@admin_required
def delete_transaction(tx_id):
    tx = StockTransaction.query.get_or_404(tx_id)
    db.session.delete(tx)
    db.session.commit()
    flash('Transaction deleted.', 'success')
    return redirect(url_for('inventory.transactions'))


# ── categories ────────────────────────────────────────────────────────────────

@inventory_bp.route('/categories', methods=['GET', 'POST'])
@login_required
@admin_required
def categories():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name', '').strip()
            if name:
                slug = name.lower().replace(' ', '-')
                if not InventoryCategory.query.filter_by(slug=slug).first():
                    db.session.add(InventoryCategory(name=name, slug=slug))
                    log_action(current_user.id, 'Add Category', f'Added: {name}')
                    db.session.commit()
                    flash(f'Category "{name}" added.', 'success')
                else:
                    flash('Category already exists.', 'danger')
        elif action == 'delete':
            cat_id = request.form.get('category_id', type=int)
            cat    = InventoryCategory.query.get_or_404(cat_id)
            log_action(current_user.id, 'Delete Category', f'Deleted: {cat.name}')
            db.session.delete(cat)
            db.session.commit()
            flash(f'Category "{cat.name}" deleted.', 'success')
        return redirect(url_for('inventory.categories'))
    return render_template('inventory/categories.html',
        categories=InventoryCategory.query.all())


# ── storage views ─────────────────────────────────────────────────────────────

@inventory_bp.route('/main-storage')
@login_required
def main_storage():
    """Main storage is SHARED across both branches — one row per item name."""
    search = request.args.get('search', '')
    cat_id = request.args.get('category_id', '')
    rows = _shared_main_items()
    if search: rows = [i for i in rows if search.lower() in i.name.lower()]
    if cat_id:  rows = [i for i in rows if i.category_id == int(cat_id)]
    categories = InventoryCategory.query.all()
    return render_template('inventory/main_storage.html',
        items=_manual_paginate(rows),
        categories=categories, search=search, selected_category=cat_id)


@inventory_bp.route('/area-storage')
@login_required
def area_storage():
    """Area storage is BRANCH-SPECIFIC."""
    search = request.args.get('search', '')
    cat_id = request.args.get('category_id', '')
    q = _branch_filter(InventoryItem.query)
    if search: q = q.filter(InventoryItem.name.ilike(f'%{search}%'))
    if cat_id: q = q.filter_by(category_id=int(cat_id))
    categories = InventoryCategory.query.all()
    return render_template('inventory/area_storage.html',
        items=_paginate(q.order_by(InventoryItem.name)),
        categories=categories, search=search, selected_category=cat_id)


# ── AJAX ──────────────────────────────────────────────────────────────────────

@inventory_bp.route('/get-items/<int:cat_id>')
@login_required
def get_items(cat_id):
    q = _branch_filter(InventoryItem.query).filter_by(category_id=cat_id)
    items = q.order_by(InventoryItem.name).all()
    return jsonify([{
        'id':   i.id, 'name': i.name,
        'unit': i.storage_unit or 'pcs',
        'main': i.main_storage_qty,
        'area': i.area_storage_qty
    } for i in items])
