import os
from flask import Flask
from flask_login import LoginManager, current_user
from models import db, User
from werkzeug.security import generate_password_hash


def create_app():
    app = Flask(__name__)
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tricoffee-inv-secret-2026-xK9mP')

    db_url = os.environ.get('DATABASE_URL', '')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    if not db_url:
        db_url = f'sqlite:///{os.path.join(basedir, "tricoffee.db")}'

    app.config['SQLALCHEMY_DATABASE_URI']        = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    lm = LoginManager()
    lm.init_app(app)
    lm.login_view             = 'auth.login'
    lm.login_message          = 'Please log in to continue.'
    lm.login_message_category = 'warning'

    @lm.user_loader
    def load_user(uid):
        from models import User as U
        return db.session.get(U, int(uid))

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
    from routes.admin_db  import admin_db_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(admin_bp,     url_prefix='/admin')
    app.register_blueprint(staff_bp,     url_prefix='/staff')
    app.register_blueprint(reports_bp,   url_prefix='/reports')
    app.register_blueprint(admin_db_bp)

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
            print("✅  Added storage_unit to inventory_items")
        if 'branch' not in item_cols:
            conn.execute(text("ALTER TABLE inventory_items ADD COLUMN branch INTEGER DEFAULT 1"))
            print("✅  Added branch to inventory_items")
        # Fix: use != 2 to catch NULL, 0, and anything that isn't explicitly branch 2
        conn.execute(text("UPDATE inventory_items SET branch = 1 WHERE branch IS NULL OR branch = 0"))
        conn.execute(text("UPDATE inventory_items SET storage_unit = 'pcs' WHERE storage_unit IS NULL OR storage_unit = ''"))
        conn.commit()

    user_cols = [c['name'] for c in inspector.get_columns('users')]
    with engine.connect() as conn:
        if 'branch' not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN branch INTEGER DEFAULT 1"))
            print("✅  Added branch to users")
        conn.execute(text("UPDATE users SET branch = 1 WHERE branch IS NULL OR branch = 0"))
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
        # Seed branch 1 items if missing
        _seed_branch1_if_missing()
        return

    cats = {
        'coffee-ingredients': InventoryCategory(name='Coffee Ingredients', slug='coffee-ingredients'),
        'packaging-supplies': InventoryCategory(name='Packaging Supplies', slug='packaging-supplies'),
        'pastries':           InventoryCategory(name='Pastries',           slug='pastries'),
        'buldak-noodles':     InventoryCategory(name='Buldak & Noodles',   slug='buldak-noodles'),
    }
    db.session.add_all(cats.values())
    db.session.commit()

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
    packaging_b2 = [
        'Double Wall Cup','16oz Cup','22oz Cup',
        'Double Wall Lid','Strawless Lid','Dome Lid',
        'Stirrer Straw','Narrow Straw','Wide Straw','Nitro','Apas',
    ]
    for name in coffee_items:
        db.session.add(InventoryItem(branch=1, name=name, category_id=cats['coffee-ingredients'].id, unit_type='g/ml', storage_unit='pcs', minimum_stock=100))
        db.session.add(InventoryItem(branch=2, name=name, category_id=cats['coffee-ingredients'].id, unit_type='g/ml', storage_unit='pcs', minimum_stock=100))
    for name in packaging_b1:
        db.session.add(InventoryItem(branch=1, name=name, category_id=cats['packaging-supplies'].id, unit_type='pcs', storage_unit='pcs', minimum_stock=50))
    for name in packaging_b2:
        db.session.add(InventoryItem(branch=2, name=name, category_id=cats['packaging-supplies'].id, unit_type='pcs', storage_unit='pcs', minimum_stock=50))
    db.session.commit()
    print('✅  Database seeded.')


def _seed_branch1_if_missing():
    """Called when categories exist but branch 1 items are missing."""
    from models import InventoryItem, InventoryCategory
    if InventoryItem.query.filter_by(branch=1).first():
        return  # already has branch 1 items

    print("⚠️  Branch 1 items missing — seeding now...")
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
    count = InventoryItem.query.filter_by(branch=1).count()
    print(f"✅  Branch 1 seeded with {count} items.")


if __name__ == '__main__':
    application = create_app()
    application.run(debug=True, host='0.0.0.0', port=5000)

app = create_app()
