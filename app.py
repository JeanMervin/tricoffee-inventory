import os
from flask import Flask
from flask_login import LoginManager, current_user
from models import db, User
from werkzeug.security import generate_password_hash


def create_app():
    app = Flask(__name__)

    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SECRET_KEY']                  = 'tricoffee-inv-secret-2026-xK9mP'
    app.config['SQLALCHEMY_DATABASE_URI']     = f'sqlite:///{os.path.join(basedir, "tricoffee.db")}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    # ── login manager ──────────────────────────────────────────────────────
    lm = LoginManager()
    lm.init_app(app)
    lm.login_view         = 'auth.login'
    lm.login_message      = 'Please log in to continue.'
    lm.login_message_category = 'warning'

    @lm.user_loader
    def load_user(uid):
        return User.query.get(int(uid))

    # ── context processor (global template vars) ───────────────────────────
    @app.context_processor
    def inject_globals():
        from datetime import datetime as _dt
        base = {
            'now':         _dt.utcnow,
            'today':       _dt.utcnow().date(),   # always available in every template
            'alert_count': 0,
        }
        try:
            if current_user.is_authenticated:
                from models import InventoryItem
                items = InventoryItem.query.all()
                base['alert_count'] = len(
                    [i for i in items if i.status in ('low_stock', 'out_of_stock')])
        except Exception:
            pass
        return base

    # ── blueprints ─────────────────────────────────────────────────────────
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

    # ── init db + seed ─────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        _seed()

    return app


def _seed():
    from models import User, InventoryCategory, InventoryItem

    # Default users
    if not User.query.first():
        db.session.add_all([
            User(username='admin', full_name='Administrator', role='admin',
                 password_hash=generate_password_hash('admin123')),
            User(username='staff', full_name='Staff Member', role='staff',
                 password_hash=generate_password_hash('staff123')),
        ])
        db.session.commit()

    if InventoryCategory.query.first():
        return  # already seeded

    # Categories
    cats = {
        'coffee-ingredients': InventoryCategory(name='Coffee Ingredients',  slug='coffee-ingredients'),
        'packaging-supplies': InventoryCategory(name='Packaging Supplies',  slug='packaging-supplies'),
        'pastries':           InventoryCategory(name='Pastries',            slug='pastries'),
    }
    db.session.add_all(cats.values())
    db.session.commit()

    # Coffee ingredients (g/ml)
    coffee_items = [
        'Non-Dairy Powder', 'Dark Cocoa Powder', 'Brown Coffee Mix', 'White Coffee Mix',
        'Washed Sugar', 'Vanilla Powder', 'Choco Powder', 'Sea Salt Cream Powder',
        'Frapped Powder Base', 'Whipped Cream Powder', 'Oreo Cookie', 'Choco Chips',
        'Hazelnut Syrup', 'French Vanilla Syrup', 'Caramel Syrup', 'Butterscotch Syrup',
        'Salted Caramel Syrup', 'Brown Sugar Syrup', 'White Chocolate Sauce',
        'Chocolate Sauce', 'Strawberry Jam', 'Coffee Jelly', 'Strawberry Syrup',
        'Condensed Milk', 'Cinnamon Powder', 'Crushed Oreo', 'Biscoff Spread',
        'Biscoff Cookie', 'Biscoff Crumbs', 'Matcha Powder',
        'Espresso Beans', 'Barako Beans', 'Arabica Beans',
    ]
    for name in coffee_items:
        db.session.add(InventoryItem(
            name=name, category_id=cats['coffee-ingredients'].id,
            unit_type='g/ml', minimum_stock=100))

    # Packaging (pcs)
    packaging_items = [
        'Double Wall Cup', '12oz Cup', '16oz Cup', '22oz Cup',
        'Double Wall Lid', '12oz Lid', 'Strawless Lid', 'Dome Lid',
        'Stirrer Straw', 'Narrow Straw', 'Wide Straw', 'Nitro', 'Apas',
    ]
    for name in packaging_items:
        db.session.add(InventoryItem(
            name=name, category_id=cats['packaging-supplies'].id,
            unit_type='pcs', minimum_stock=50))

    db.session.commit()
    print('✅  Database seeded with default users and inventory items.')


if __name__ == '__main__':
    application = create_app()
    application.run(debug=True, host='0.0.0.0', port=5000)

app = create_app()