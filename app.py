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

    # ── connection pool resilience for serverless Postgres (Neon) ────────────
    # Neon scales to zero after ~5 min idle. Without pre_ping, SQLAlchemy will
    # try to reuse a pooled connection that Neon already closed on its end,
    # causing "SSL connection has been closed unexpectedly" -> unhandled 500.
    # pool_pre_ping tests each connection with a cheap query before using it
    # and transparently reconnects if it's gone stale.
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 280,   # recycle connections before Neon's own timeout
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
        return  # already seeded, don't duplicate

    cats = {
        'coffee-ingredients': InventoryCategory(name='Coffee Ingredients',  slug='coffee-ingredients'),
        'packaging-supplies': InventoryCategory(name='Packaging Supplies',  slug='packaging-supplies'),
        'pastries':           InventoryCategory(name='Pastries',            slug='pastries'),
        'buldak-noodles':     InventoryCategory(name='Buldak & Noodles',    slug='buldak-noodles'),
    }
    db.session.add_all(cats.values())
    db.session.commit()

    # ── BRANCH 1 — Coffee Ingredients (from actual daily reports, union of all dates) ──
    b1_coffee = [
        'Arabica Beans', 'Barako Beans', 'Biscoff Crumbs', 'Biscoff Spread',
        'Blueberry Jam', 'Blueberry Syrup', 'Brown Coffee Mix', 'Brown Sugar Syrup',
        'Bruna', 'Butterscotch Syrup', 'Caramel Gourmet Syrup', 'Caramel Sauce',
        'Choco Droplets', 'Chocolate Sauce Saitam', 'Chocolate Syrup Venezia',
        'Choco Powder', 'Cinnamon Powder', 'Coffee Jelly', 'Condensed Milk',
        'Creme Brulee Powder', 'Crushed Oreo', 'Dark Cocoa Powder', 'Espresso Beans',
        'Everwhip', 'Frapped Powder Base', 'French Vanilla Syrup', 'Mango Jam',
        'Mango Syrup', 'Matcha Powder', 'Oatside', 'Oreo Cookie (Big)',
        'Oreo Cookie (Mini)', 'Salted Caramel Syrup', 'Sea Salt Cream Powder',
        'Strawberry Jam', 'Strawberry Syrup', 'Taro Powder', 'Tipco',
        'Vanilla Powder', 'Washed Sugar', 'White Chocolate Sauce', 'White Coffee Mix',
    ]
    for name in b1_coffee:
        db.session.add(InventoryItem(branch=1, name=name, category_id=cats['coffee-ingredients'].id,
            unit_type='g/ml', storage_unit='pcs', minimum_stock=100))

    # ── BRANCH 1 — Packaging Supplies ──
    b1_packaging = [
        '12oz Cup', '12oz Lid', '16oz Cup', '22oz Cup', 'Apas', 'Dome Lid',
        'Double Wall Cup', 'Double Wall Lid', 'Narrow Straw', 'Nitro',
        'Stirrer Straw', 'Strawless Lid', 'Wide Straw',
    ]
    for name in b1_packaging:
        db.session.add(InventoryItem(branch=1, name=name, category_id=cats['packaging-supplies'].id,
            unit_type='pcs', storage_unit='pcs', minimum_stock=50))

    # ── BRANCH 1 — Pastries (note: "Biscoff Cookie" here is separate from the
    #     Coffee Ingredients one of the same name — confirmed from actual reports) ──
    b1_pastries = [
        'Biscoff Bites', 'Biscoff Cookie', 'Brownie Cookie', 'Dulce De Leche',
        'Nutella Cookie', 'Pistachio Cookie', 'Red Velvet Cookie', 'Scoopable Cookie',
    ]
    for name in b1_pastries:
        db.session.add(InventoryItem(branch=1, name=name, category_id=cats['pastries'].id,
            unit_type='pcs', storage_unit='pcs', minimum_stock=5))

    # ── BRANCH 2 — Coffee Ingredients (from actual daily report, July 13) ──
    b2_coffee = [
        'Biscoff Cookie', 'Biscoff Crumbs', 'Biscoff Spread', 'Brown Coffee Mix',
        'Brown Sugar Syrup', 'Bruna', 'Butterscotch Syrup', 'Caramel Gourmet Syrup',
        'Caramel Sauce', 'Choco Droplets', 'Chocolate Sauce Saitam', 'Chocolate Sauce Venezia',
        'Choco Powder', 'Cinnamon Powder', 'Coffee Jelly', 'Condensed Milk', 'Crushed Oreo',
        'Dark Cocoa Powder', 'Espresso Beans', 'Everwhip', 'Frapped Powder Base',
        'French Vanilla Syrup', 'Hazelnut Syrup', 'Matcha Powder', 'Non-Dairy Powder',
        'Oatside', 'Oreo Cookie (Big)', 'Oreo Cookie (Mini)', 'Salted Caramel Syrup',
        'Sea Salt Cream Powder', 'Strawberry Jam', 'Strawberry Syrup', 'Vanilla Powder',
        'Washed Sugar', 'Whipped Cream Powder', 'White Chocolate Sauce', 'White Coffee Mix',
    ]
    for name in b2_coffee:
        db.session.add(InventoryItem(branch=2, name=name, category_id=cats['coffee-ingredients'].id,
            unit_type='g/ml', storage_unit='pcs', minimum_stock=100))

    # ── BRANCH 2 — Packaging Supplies (no 12oz cup/lid) ──
    b2_packaging = [
        '16oz Cup', '22oz Cup', 'Apas', 'Dome Lid', 'Double Wall Cup', 'Double Wall Lid',
        'Narrow Straw', 'Nitro', 'Stirrer Straw', 'Strawless Lid', 'Wide Straw',
    ]
    for name in b2_packaging:
        db.session.add(InventoryItem(branch=2, name=name, category_id=cats['packaging-supplies'].id,
            unit_type='pcs', storage_unit='pcs', minimum_stock=50))

    # ── BRANCH 2 — Buldak & Noodles ──
    b2_buldak = [
        'Buldak Carbonara', 'Buldak Cheese', 'Buldak Creamy Carbonara', 'Buldak Swicy',
        'Jin Mild', 'Jin Spicy', 'Ottogi Cheese', 'Ottogi Spicy', 'Ottogi Stir-fry',
        'Seaweed', 'Yoppoki',
    ]
    for name in b2_buldak:
        db.session.add(InventoryItem(branch=2, name=name, category_id=cats['buldak-noodles'].id,
            unit_type='pcs', storage_unit='pcs', minimum_stock=5))

    db.session.commit()
    logger.info('Database seeded with full item catalog for both branches.')


if __name__ == '__main__':
    app = create_app()
    app.run(debug=False, host='0.0.0.0', port=5000)

app = create_app()
