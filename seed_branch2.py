"""
Run once to seed Branch 2 (Tricoffee 2) items.
Usage: python seed_branch2.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from models import db, InventoryCategory, InventoryItem

app = create_app()

with app.app_context():
    # Check if branch 2 items already exist
    existing = InventoryItem.query.filter_by(branch=2).count()
    if existing > 0:
        print(f"Branch 2 already has {existing} items. Skipping.")
        sys.exit(0)

    # Get existing categories (shared across branches)
    cats = {c.slug: c for c in InventoryCategory.query.all()}

    # Create missing categories if needed
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
    for name in coffee_items:
        db.session.add(InventoryItem(
            branch=2, name=name,
            category_id=cats['coffee-ingredients'].id,
            unit_type='g/ml', storage_unit='pcs', minimum_stock=100
        ))

    # Branch 2 packaging — no 12oz Cup or 12oz Lid
    packaging_b2 = [
        'Double Wall Cup','16oz Cup','22oz Cup',
        'Double Wall Lid','Strawless Lid','Dome Lid',
        'Stirrer Straw','Narrow Straw','Wide Straw','Nitro','Apas',
    ]
    for name in packaging_b2:
        db.session.add(InventoryItem(
            branch=2, name=name,
            category_id=cats['packaging-supplies'].id,
            unit_type='pcs', storage_unit='pcs', minimum_stock=50
        ))

    db.session.commit()
    total = InventoryItem.query.filter_by(branch=2).count()
    print(f"✅ Branch 2 seeded with {total} items.")
