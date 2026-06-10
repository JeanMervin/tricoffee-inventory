from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from models import db, User, ActivityLog
from utils import admin_required, log_action
from datetime import datetime

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/')
@login_required
@admin_required
def index():
    return redirect(url_for('admin.users'))


# ── users ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=all_users)


@admin_bp.route('/users/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_user():
    if request.method == 'POST':
        username  = request.form.get('username', '').strip()
        password  = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        role      = request.form.get('role', 'staff')

        if not username or not password:
            flash('Username and password are required.', 'danger')
        elif len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
        else:
            user = User(username=username,
                        password_hash=generate_password_hash(password),
                        full_name=full_name, role=role,
                        created_at=datetime.utcnow())
            db.session.add(user)
            log_action(current_user.id, 'Add User', f'Created user: {username} ({role})')
            db.session.commit()
            flash(f'User "{username}" created.', 'success')
            return redirect(url_for('admin.users'))

    return render_template('admin/add_user.html')


@admin_bp.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.full_name = request.form.get('full_name', user.full_name).strip()
        user.role      = request.form.get('role', user.role)
        user.is_active = (request.form.get('is_active') == 'on')
        new_pw = request.form.get('new_password', '')
        if new_pw:
            if len(new_pw) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                return render_template('admin/edit_user.html', user=user)
            user.password_hash = generate_password_hash(new_pw)
        log_action(current_user.id, 'Edit User', f'Edited user: {user.username}')
        db.session.commit()
        flash(f'User "{user.username}" updated.', 'success')
        return redirect(url_for('admin.users'))
    return render_template('admin/edit_user.html', user=user)


@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin.users'))
    username = user.username
    log_action(current_user.id, 'Delete User', f'Deleted user: {username}')
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{username}" deleted.', 'success')
    return redirect(url_for('admin.users'))


# ── activity logs ─────────────────────────────────────────────────────────────

@admin_bp.route('/logs')
@login_required
@admin_required
def logs():
    uid    = request.args.get('user_id', '')
    action = request.args.get('action', '')
    page   = request.args.get('page', 1, type=int)

    q = ActivityLog.query
    if uid:    q = q.filter_by(user_id=uid)
    if action: q = q.filter(ActivityLog.action.ilike(f'%{action}%'))

    logs_page  = q.order_by(ActivityLog.timestamp.desc()).paginate(
        page=page, per_page=30, error_out=False)
    all_users  = User.query.all()
    return render_template('admin/logs.html',
        logs=logs_page, users=all_users,
        selected_user=uid, selected_action=action)
