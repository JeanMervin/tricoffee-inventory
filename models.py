from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name     = db.Column(db.String(100), default='')
    role          = db.Column(db.String(20), default='staff')   # 'admin' | 'staff'
    branch        = db.Column(db.Integer,     default=1)           # 1 = Tricoffee 1, 2 = Tricoffee 2
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    transactions = db.relationship('StockTransaction', backref='user', lazy=True)
    logs         = db.relationship('ActivityLog',      backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'admin'


class InventoryCategory(db.Model):
    __tablename__ = 'inventory_categories'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    slug       = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship(
        'InventoryItem', backref='category',
        lazy=True, cascade='all, delete-orphan'
    )


class InventoryItem(db.Model):
    __tablename__ = 'inventory_items'
    id               = db.Column(db.Integer, primary_key=True)
    branch           = db.Column(db.Integer, default=1)  # 1 = Tricoffee 1, 2 = Tricoffee 2
    category_id      = db.Column(db.Integer, db.ForeignKey('inventory_categories.id'), nullable=False)
    name             = db.Column(db.String(100), nullable=False)
    unit_type        = db.Column(db.String(20),  default='g/ml')  # weigh-in unit
    storage_unit     = db.Column(db.String(20),  default='pcs')   # bulk storage unit
    main_storage_qty = db.Column(db.Float,       default=0)
    area_storage_qty = db.Column(db.Float,       default=0)
    minimum_stock    = db.Column(db.Float,       default=10)
    created_at       = db.Column(db.DateTime,    default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime,    default=datetime.utcnow)

    transactions = db.relationship(
        'StockTransaction', backref='item',
        lazy=True, cascade='all, delete-orphan'
    )

    @property
    def total_qty(self):
        return self.main_storage_qty + self.area_storage_qty

    @property
    def status(self):
        if self.area_storage_qty <= 0:
            return 'out_of_stock'
        elif self.area_storage_qty <= self.minimum_stock:
            return 'low_stock'
        return 'in_stock'

    @property
    def status_label(self):
        return {'in_stock': 'In Stock', 'low_stock': 'Low Stock',
                'out_of_stock': 'Out of Stock'}.get(self.status, 'Unknown')

    @property
    def status_badge(self):
        return {'in_stock': 'success', 'low_stock': 'warning',
                'out_of_stock': 'danger'}.get(self.status, 'secondary')


class StockTransaction(db.Model):
    __tablename__ = 'stock_transactions'
    id               = db.Column(db.Integer, primary_key=True)
    item_id          = db.Column(db.Integer, db.ForeignKey('inventory_items.id'), nullable=False)
    transaction_type = db.Column(db.String(30), nullable=False)
    # Types: supplier_in | transfer_to_area | stock_out | adjustment_main | adjustment_area
    quantity         = db.Column(db.Float,  nullable=False)
    remarks          = db.Column(db.Text,   default='')
    user_id          = db.Column(db.Integer, db.ForeignKey('users.id'))
    transaction_date = db.Column(db.DateTime, default=datetime.utcnow)

    LABELS = {
        'supplier_in':      'Stock In (Supplier)',
        'transfer_to_area': 'Transfer to Area',
        'stock_out':        'Stock Out (Used)',
        'adjustment_main':  'Adjustment (Main)',
        'adjustment_area':  'Adjustment (Area)',
        'count_open':       'Opening Count (Weigh-In)',
    }

    @property
    def type_label(self):
        return self.LABELS.get(self.transaction_type, self.transaction_type)

    @property
    def type_color(self):
        return {
            'supplier_in':      'success',
            'transfer_to_area': 'info',
            'stock_out':        'danger',
            'adjustment_main':  'secondary',
            'adjustment_area':  'secondary',
            'count_open':       'primary',
        }.get(self.transaction_type, 'secondary')


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'))
    action     = db.Column(db.String(100), nullable=False)
    details    = db.Column(db.Text,   default='')
    ip_address = db.Column(db.String(50), default='')
    timestamp  = db.Column(db.DateTime,   default=datetime.utcnow)
