from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, InventoryItem, InventoryCategory, User
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
    """Shows live database branch counts — safe read-only view."""
    from sqlalchemy import text
    engine = db.engine
    with engine.connect() as conn:
        item_rows  = conn.execute(text("SELECT branch, COUNT(*) as cnt FROM inventory_items GROUP BY branch ORDER BY branch")).fetchall()
        user_rows  = conn.execute(text("SELECT branch, role, COUNT(*) as cnt FROM users GROUP BY branch, role ORDER BY branch")).fetchall()
        total      = conn.execute(text("SELECT COUNT(*) FROM inventory_items")).scalar()
        null_items = conn.execute(text("SELECT COUNT(*) FROM inventory_items WHERE branch IS NULL OR branch = 0")).scalar()

    return render_template('admin/db_status.html',
        item_rows=item_rows,
        user_rows=user_rows,
        total=total,
        null_items=null_items)


@admin_db_bp.route('/admin/db-fix', methods=['POST'])
@login_required
@admin_only
def db_fix():
    """One-time fix: set NULL/0 branch items to branch 1, seed if missing."""
    engine = db.engine
    with engine.connect() as conn:
        conn.execute(text("UPDATE inventory_items SET branch = 1 WHERE branch IS NULL OR branch = 0"))
        conn.execute(text("UPDATE inventory_items SET storage_unit = 'pcs' WHERE storage_unit IS NULL OR storage_unit = ''"))
        conn.execute(text("UPDATE users SET branch = 0 WHERE role = 'admin'"))
        conn.commit()

    # Auto-seed branch 1 if still missing
    from app import _seed_branch1_if_missing
    _seed_branch1_if_missing()

    flash('Database fixed successfully.', 'success')
    return redirect(url_for('admin_db.db_status'))
