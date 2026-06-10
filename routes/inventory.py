from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import db, InventoryItem, InventoryCategory, StockTransaction
from utils import admin_required, log_action
from datetime import datetime

inventory_bp = Blueprint('inventory', __name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _paginate(query, per_page=20):
    page = request.args.get('page', 1, type=int)
    return query.paginate(page=page, per_page=per_page, error_out=False)


# ── list views ───────────────────────────────────────────────────────────────

@inventory_bp.route('/')
@login_required
@admin_required
def list_all():
    search      = request.args.get('search', '')
    cat_id      = request.args.get('category_id', '')
    status_f    = request.args.get('status', '')
    sort        = request.args.get('sort', 'name')

    q = InventoryItem.query
    if search:  q = q.filter(InventoryItem.name.ilike(f'%{search}%'))
    if cat_id:  q = q.filter_by(category_id=cat_id)
    if sort == 'stock_asc':   q = q.order_by(InventoryItem.area_storage_qty.asc())
    elif sort == 'stock_desc': q = q.order_by(InventoryItem.area_storage_qty.desc())
    else:       q = q.order_by(InventoryItem.name.asc())

    all_rows = q.all()
    if status_f:
        all_rows = [i for i in all_rows if i.status == status_f]

    items      = _paginate(q)
    categories = InventoryCategory.query.all()
    return render_template('inventory/list.html',
        items=items, categories=categories, all_rows=all_rows,
        search=search, selected_category=cat_id,
        selected_status=status_f, sort=sort,
        current_category=None)


@inventory_bp.route('/category/<slug>')
@login_required
@admin_required
def list_by_category(slug):
    category = InventoryCategory.query.filter_by(slug=slug).first_or_404()
    search   = request.args.get('search', '')
    sort     = request.args.get('sort', 'name')

    q = InventoryItem.query.filter_by(category_id=category.id)
    if search: q = q.filter(InventoryItem.name.ilike(f'%{search}%'))
    if sort == 'stock_asc':   q = q.order_by(InventoryItem.area_storage_qty.asc())
    elif sort == 'stock_desc': q = q.order_by(InventoryItem.area_storage_qty.desc())
    else: q = q.order_by(InventoryItem.name.asc())

    items      = _paginate(q)
    categories = InventoryCategory.query.all()
    return render_template('inventory/list.html',
        items=items, categories=categories, all_rows=q.all(),
        search=search, selected_category=str(category.id),
        selected_status='', sort=sort,
        current_category=category)


# ── CRUD ─────────────────────────────────────────────────────────────────────

@inventory_bp.route('/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_item():
    categories = InventoryCategory.query.all()
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        cat_id   = request.form.get('category_id')
        unit     = request.form.get('unit_type', 'pcs')
        min_stk  = request.form.get('minimum_stock', 10, type=float)

        if not name or not cat_id:
            flash('Name and category are required.', 'danger')
        elif InventoryItem.query.filter_by(name=name, category_id=cat_id).first():
            flash('An item with that name already exists in this category.', 'danger')
        else:
            item = InventoryItem(name=name, category_id=cat_id, unit_type=unit,
                                 main_storage_qty=0, area_storage_qty=0,
                                 minimum_stock=min_stk,
                                 created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            db.session.add(item)
            log_action(current_user.id, 'Add Item', f'Added: {name}')
            db.session.commit()
            flash(f'Item "{name}" added successfully.', 'success')
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
        item.category_id   = request.form.get('category_id', item.category_id)
        item.unit_type     = request.form.get('unit_type', item.unit_type)
        item.minimum_stock = request.form.get('minimum_stock', item.minimum_stock, type=float)
        item.updated_at    = datetime.utcnow()
        log_action(current_user.id, 'Edit Item', f'Edited: {item.name}')
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


# ── stock operations (admin) ──────────────────────────────────────────────────

@inventory_bp.route('/stock-in', methods=['GET', 'POST'])
@login_required
@admin_required
def stock_in():
    """Admin: add stock from supplier → main storage."""
    categories = InventoryCategory.query.all()
    if request.method == 'POST':
        item_id  = request.form.get('item_id', type=int)
        qty      = request.form.get('quantity', type=float)
        remarks  = request.form.get('remarks', '')

        if not item_id or not qty or qty <= 0:
            flash('Please select an item and enter a valid quantity.', 'danger')
        else:
            item = InventoryItem.query.get_or_404(item_id)
            item.main_storage_qty += qty
            item.updated_at = datetime.utcnow()
            db.session.add(StockTransaction(
                item_id=item_id, transaction_type='supplier_in',
                quantity=qty, remarks=remarks, user_id=current_user.id,
                transaction_date=datetime.utcnow()))
            log_action(current_user.id, 'Stock In (Supplier)',
                       f'+{qty} {item.unit_type} of {item.name} → main storage')
            db.session.commit()
            flash(f'Added {qty} {item.unit_type} of {item.name} to main storage.', 'success')
            return redirect(url_for('inventory.stock_in'))

    items = InventoryItem.query.order_by(InventoryItem.name).all()
    return render_template('inventory/stock_in.html', items=items, categories=categories)


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
               f'{storage_type} storage of {item.name} set to {qty} {item.unit_type}')
    db.session.commit()
    flash(f'Adjustment saved for "{item.name}".', 'success')
    return redirect(url_for('inventory.list_all'))


# ── transactions ─────────────────────────────────────────────────────────────

@inventory_bp.route('/transactions')
@login_required
@admin_required
def transactions():
    item_id  = request.args.get('item_id', '')
    ttype    = request.args.get('type', '')
    q = StockTransaction.query
    if item_id: q = q.filter_by(item_id=item_id)
    if ttype:   q = q.filter_by(transaction_type=ttype)
    txs   = _paginate(q.order_by(StockTransaction.transaction_date.desc()), per_page=25)
    items = InventoryItem.query.order_by(InventoryItem.name).all()
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
    flash('Transaction record deleted.', 'success')
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

    cats = InventoryCategory.query.all()
    return render_template('inventory/categories.html', categories=cats)


# ── storage views ─────────────────────────────────────────────────────────────

@inventory_bp.route('/main-storage')
@login_required
@admin_required
def main_storage():
    search = request.args.get('search', '')
    cat_id = request.args.get('category_id', '')
    q = InventoryItem.query
    if search: q = q.filter(InventoryItem.name.ilike(f'%{search}%'))
    if cat_id: q = q.filter_by(category_id=cat_id)
    items      = _paginate(q.order_by(InventoryItem.name))
    categories = InventoryCategory.query.all()
    return render_template('inventory/main_storage.html',
        items=items, categories=categories,
        search=search, selected_category=cat_id)


@inventory_bp.route('/area-storage')
@login_required
def area_storage():
    search = request.args.get('search', '')
    cat_id = request.args.get('category_id', '')
    q = InventoryItem.query
    if search: q = q.filter(InventoryItem.name.ilike(f'%{search}%'))
    if cat_id: q = q.filter_by(category_id=cat_id)
    items      = _paginate(q.order_by(InventoryItem.name))
    categories = InventoryCategory.query.all()
    return render_template('inventory/area_storage.html',
        items=items, categories=categories,
        search=search, selected_category=cat_id)


# ── AJAX helpers ──────────────────────────────────────────────────────────────

@inventory_bp.route('/get-items/<int:cat_id>')
@login_required
def get_items(cat_id):
    items = InventoryItem.query.filter_by(category_id=cat_id).order_by(InventoryItem.name).all()
    return jsonify([{
        'id':   i.id, 'name': i.name, 'unit': i.unit_type,
        'main': i.main_storage_qty, 'area': i.area_storage_qty
    } for i in items])
