import os
import logging
from flask import Flask, render_template, request
from flask_login import LoginManager, current_user
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash
from models import db, User

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s [%(name)s] %(message)s')
logger = logging.getLogger('tricoffee')


def create_app():
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))

    db_url = os.environ.get('DATABASE_URL', '')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    is_production = db_url.startswith('postgresql://')
    if not db_url:
        db_url = f'sqlite:///{os.path.join(basedir, "tricoffee.db")}'

    app.config['SQLALCHEMY_DATABASE_URI']        = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Connection pool resilience for serverless Postgres (Neon scale-to-zero)
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
    }

    secret = os.environ.get('SECRET_KEY')
    if not secret:
        secret = 'insecure-dev-key-do-not-use-in-production'
        if is_production:
            logger.warning('⚠️  SECRET_KEY not set in environment! Sessions are not secure.')
    app.config['SECRET_KEY'] = secret

    from datetime import timedelta
    app.config['SESSION_COOKIE_HTTPONLY']    = True
    app.config['SESSION_COOKIE_SAMESITE']    = 'Lax'
    app.config['SESSION_COOKIE_SECURE']      = is_production
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.config['MAX_CONTENT_LENGTH']         = 2 * 1024 * 1024
    app.config['WTF_CSRF_TIME_LIMIT']        = None

    from flask_wtf import CSRFProtect
    csrf = CSRFProtect()
    csrf.init_app(app)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)

    lm = LoginManager()
    lm.init_app(app)
    lm.login_view             = 'auth.login'
    lm.login_message          = 'Please log in to continue.'
    lm.login_message_category = 'warning'

    @lm.user_loader
    def load_user(uid):
        return db.session.get(User, int(uid))

    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
        limiter = Limiter(get_remote_address, app=app, default_limits=[])
        app.limiter = limiter
    except ImportError:
        logger.warning('flask-limiter not installed — IP-based login throttling disabled.')
        app.limiter = None

    @app.context_processor
    def inject_globals():
        from datetime import datetime as _dt
        from flask import session
        base = {'now': _dt.utcnow, 'today': _dt.utcnow().date(), 'alert_count': 0}
        try:
            if current_user.is_authenticated:
                from models import InventoryItem
                if current_user.role == 'admin':
                    branch = session.get('admin_branch', 0)
                    q = InventoryItem.query
                    if branch:
                        q = q.filter_by(branch=branch)
                    items = q.all()
                else:
                    items = InventoryItem.query.filter_by(branch=current_user.branch).all()
                base['alert_count'] = len([i for i in items if i.status in ('low_stock', 'out_of_stock')])
        except Exception:
            pass
        return base

    from routes.auth      import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.inventory import inventory_bp
    from routes.admin     import admin_bp
    from routes.staff     import staff_bp
    from routes.reports   import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(admin_bp,     url_prefix='/admin')
    app.register_blueprint(staff_bp,     url_prefix='/staff')
    app.register_blueprint(reports_bp,   url_prefix='/reports')

    try:
        from routes.admin_db import admin_db_bp
        app.register_blueprint(admin_db_bp)
    except ImportError:
        pass

    if app.limiter:
        app.limiter.limit('10 per minute')(app.view_functions['auth.login'])

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options']        = 'DENY'
        response.headers['Referrer-Policy']        = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy']     = 'geolocation=(), microphone=(), camera=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self';"
        )
        if is_production:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    @app.errorhandler(400)
    def bad_request(e):
        logger.warning('400 Bad Request on %s %s — %s', request.method, request.path, e)
        return render_template('errors/400.html'), 400

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(429)
    def rate_limited(e):
        return render_template('errors/429.html'), 429

    @app.errorhandler(413)
    def too_large(e):
        return render_template('errors/400.html'), 413

    @app.errorhandler(500)
    def server_error(e):
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.exception('Unhandled server error on %s %s', request.method, request.path)
        return render_template('errors/500.html'), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.exception('Unhandled exception on %s %s', request.method, request.path)
        return render_template('errors/500.html'), 500

    with app.app_context():
        db.create_all()
        _migrate()
        _seed()

    return app


def _migrate():
    from sqlalchemy import text, inspect
    engine    = db.engine
    inspector = inspect(engine)

    item_cols = [c['name'] for c in inspector.get_columns('inventory_items')]
    with engine.connect() as conn:
        if 'storage_unit' not in item_cols:
            conn.execute(text("ALTER TABLE inventory_items ADD COLUMN storage_unit VARCHAR(20) DEFAULT 'pcs'"))
        if 'branch' not in item_cols:
            conn.execute(text("ALTER TABLE inventory_items ADD COLUMN branch INTEGER DEFAULT 1"))
        conn.execute(text("UPDATE inventory_items SET branch = 1 WHERE branch IS NULL OR branch = 0"))
        conn.execute(text("UPDATE inventory_items SET storage_unit = 'pcs' WHERE storage_unit IS NULL OR storage_unit = ''"))
        conn.commit()

    user_cols = [c['name'] for c in inspector.get_columns('users')]
    with engine.connect() as conn:
        if 'branch' not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN branch INTEGER DEFAULT 1"))
        for col, ddl in [
            ('failed_attempts', "ALTER TABLE users ADD COLUMN failed_attempts INTEGER DEFAULT 0"),
            ('locked_until',    "ALTER TABLE users ADD COLUMN locked_until TIMESTAMP"),
            ('last_login_at',   "ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP"),
            ('last_login_ip',   "ALTER TABLE users ADD COLUMN last_login_ip VARCHAR(64)"),
        ]:
            if col not in user_cols:
                conn.execute(text(ddl))
        conn.execute(text("UPDATE users SET branch = 1 WHERE branch IS NULL OR (branch = 0 AND role = 'staff')"))
        conn.execute(text("UPDATE users SET branch = 0 WHERE role = 'admin'"))
        conn.commit()


def _seed():
    from models import User, InventoryCategory, InventoryItem

    if not User.query.filter_by(username='admin').first():
        db.session.add(User(username='admin', full_name='Administrator', role='admin', branch=0,
                            password_hash=generate_password_hash('admin123')))
    if not User.query.filter_by(username='staff').first():
        db.session.add(User(username='staff', full_name='Tricoffee 1 Staff', role='staff', branch=1,
                            password_hash=generate_password_hash('staff123')))
    if not User.query.filter_by(username='staff2').first():
        db.session.add(User(username='staff2', full_name='Tricoffee 2 Staff', role='staff', branch=2,
                            password_hash=generate_password_hash('staff123')))
    db.session.commit()

    if InventoryCategory.query.first():
        return


if __name__ == '__main__':
    app = create_app()
    app.run(debug=False, host='0.0.0.0', port=5000)

app = create_app()
