from functools import wraps
from flask import redirect, url_for, flash, request
from flask_login import current_user
from models import db, ActivityLog
from datetime import datetime


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Administrator access required.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def log_action(user_id, action, details=''):
    """Add an activity log entry (caller must commit)."""
    entry = ActivityLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=request.remote_addr,
        timestamp=datetime.utcnow()
    )
    db.session.add(entry)


def fmt_qty(value):
    """Return a clean number string (drop .0 for whole numbers)."""
    if value is None:
        return '0'
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(round(value, 2))
