from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, InventoryItem, InventoryCategory
from sqlalchemy import text

admin_db_bp = Blueprint('admin_db', __name__)


def admin_only(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin only.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


@admin_db_bp.route('/admin/db-status')
@login_required
@admin_only
def db_status():
    engine = db.engine
    with engine.connect() as conn:
        item_rows  = conn.execute(text("SELECT branch, COUNT(*) as cnt FROM inventory_items GROUP BY branch ORDER BY branch")).fetchall()
        user_rows  = conn.execute(text("SELECT branch, role, COUNT(*) as cnt FROM users GROUP BY branch, role ORDER BY branch")).fetchall()
        total      = conn.execute(text("SELECT COUNT(*) FROM inventory_items")).scalar()
        null_items = conn.execute(text("SELECT COUNT(*) FROM inventory_items WHERE branch IS NULL OR branch = 0")).scalar()

    b1_count = next((r[1] for r in item_rows if r[0] == 1), 0)
    b2_count = next((r[1] for r in item_rows if r[0] == 2), 0)

    return render_template('admin/db_status.html',
        item_rows=item_rows, user_rows=user_rows,
        total=total, null_items=null_items,
        b1_count=b1_count, b2_count=b2_count)


@admin_db_bp.route('/admin/db-fix', methods=['POST'])
@login_required
@admin_only
def db_fix():
    engine = db.engine
    with engine.connect() as conn:
        conn.execute(text("UPDATE inventory_items SET branch = 1 WHERE branch IS NULL OR branch = 0"))
        conn.execute(text("UPDATE inventory_items SET storage_unit = 'pcs' WHERE storage_unit IS NULL OR storage_unit = ''"))
        conn.execute(text("UPDATE users SET branch = 0 WHERE role = 'admin'"))
        conn.commit()
    _seed_branch1_if_missing()
    _seed_branch2_if_missing()
    flash('Branch 1 fixed and seeded.', 'success')
    return redirect(url_for('admin_db.db_status'))


@admin_db_bp.route('/admin/db-fix-branch2', methods=['POST'])
@login_required
@admin_only
def db_fix_branch2():
    _seed_branch2_if_missing()
    flash('Branch 2 items seeded successfully.', 'success')
    return redirect(url_for('admin_db.db_status'))


def _seed_branch1_if_missing():
    if InventoryItem.query.filter_by(branch=1).first():
        return
    cats = {c.slug: c for c in InventoryCategory.query.all()}
    coffee_items = [
        'Non-Dairy Powder','Dark Cocoa Powder','Brown Coffee Mix','White Coffee Mix',
        'Washed Sugar','Vanilla Powder','Choco Powder','Sea Salt Cream Powder',
        'Frapped Powder Base','Whipped Cream Powder','Oreo Cookie','Choco Chips',
        'Hazelnut Syrup','French Vanilla Syrup','Caramel Syrup','Butterscotch Syrup',
        'Salted Caramel Syrup','Brown Sugar Syrup','White Chocolate Sauce',
        'Chocolate Sauce','Strawberry Jam','Coffee Jelly','Strawberry Syrup',
        'Condensed Milk','Cinnamon Powder','Crushed Oreo','Biscoff Spread',
        'Biscoff Cookie','Biscoff Crumbs','Matcha Powder',
        'Espresso Beans','Barako Beans','Arabica Beans',
    ]
    packaging_b1 = [
        'Double Wall Cup','12oz Cup','16oz Cup','22oz Cup',
        'Double Wall Lid','12oz Lid','Strawless Lid','Dome Lid',
        'Stirrer Straw','Narrow Straw','Wide Straw','Nitro','Apas',
    ]
    if 'coffee-ingredients' in cats:
        for name in coffee_items:
            db.session.add(InventoryItem(branch=1, name=name, category_id=cats['coffee-ingredients'].id, unit_type='g/ml', storage_unit='pcs', minimum_stock=100))
    if 'packaging-supplies' in cats:
        for name in packaging_b1:
            db.session.add(InventoryItem(branch=1, name=name, category_id=cats['packaging-supplies'].id, unit_type='pcs', storage_unit='pcs', minimum_stock=50))
    db.session.commit()


def _seed_branch2_if_missing():
    if InventoryItem.query.filter_by(branch=2).first():
        return
    cats = {c.slug: c for c in InventoryCategory.query.all()}

    # Create Buldak & Noodles category if missing
    if 'buldak-noodles' not in cats:
        cat = InventoryCategory(name='Buldak & Noodles', slug='buldak-noodles')
        db.session.add(cat)
        db.session.flush()
        cats['buldak-noodles'] = cat

    coffee_items = [
        'Non-Dairy Powder','Dark Cocoa Powder','Brown Coffee Mix','White Coffee Mix',
        'Washed Sugar','Vanilla Powder','Choco Powder','Sea Salt Cream Powder',
        'Frapped Powder Base','Whipped Cream Powder','Oreo Cookie','Choco Chips',
        'Hazelnut Syrup','French Vanilla Syrup','Caramel Syrup','Butterscotch Syrup',
        'Salted Caramel Syrup','Brown Sugar Syrup','White Chocolate Sauce',
        'Chocolate Sauce','Strawberry Jam','Coffee Jelly','Strawberry Syrup',
        'Condensed Milk','Cinnamon Powder','Crushed Oreo','Biscoff Spread',
        'Biscoff Cookie','Biscoff Crumbs','Matcha Powder',
        'Espresso Beans','Barako Beans','Arabica Beans',
    ]
    packaging_b2 = [
        'Double Wall Cup','16oz Cup','22oz Cup',
        'Double Wall Lid','Strawless Lid','Dome Lid',
        'Stirrer Straw','Narrow Straw','Wide Straw','Nitro','Apas',
    ]
    if 'coffee-ingredients' in cats:
        for name in coffee_items:
            db.session.add(InventoryItem(branch=2, name=name, category_id=cats['coffee-ingredients'].id, unit_type='g/ml', storage_unit='pcs', minimum_stock=100))
    if 'packaging-supplies' in cats:
        for name in packaging_b2:
            db.session.add(InventoryItem(branch=2, name=name, category_id=cats['packaging-supplies'].id, unit_type='pcs', storage_unit='pcs', minimum_stock=50))
    db.session.commit()
    print(f"✅  Branch 2 seeded with {InventoryItem.query.filter_by(branch=2).count()} items.")
