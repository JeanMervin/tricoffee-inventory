from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User
from utils import log_action
from datetime import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index') if current_user.role == 'admin' else url_for('staff.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        ip       = request.remote_addr

        user = User.query.filter_by(username=username).first()

        # Generic message for every failure path — never reveal whether the
        # username exists, whether the account is locked, etc.
        generic_error = 'Invalid username or password, or the account is temporarily locked. Please try again in a few minutes.'

        if user and user.is_locked():
            flash(generic_error, 'danger')
            return render_template('login.html')

        if user and user.check_password(password) and user.is_active:
            user.register_successful_login(ip)
            login_user(user)
            session.permanent = True
            log_action(user.id, 'Login', f'{user.username} logged in from {ip}')
            db.session.commit()
            next_page = request.args.get('next')
            if user.role == 'admin':
                return redirect(next_page or url_for('dashboard.index'))
            return redirect(next_page or url_for('staff.dashboard'))

        # Failed attempt — register it if the user exists, but always show
        # the same generic message so failed logins can't be used to guess
        # valid usernames.
        if user:
            user.register_failed_attempt()
            db.session.commit()

        flash(generic_error, 'danger')

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    log_action(current_user.id, 'Logout', f'{current_user.username} logged out')
    db.session.commit()
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
