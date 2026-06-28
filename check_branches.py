import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from app import create_app
from models import db, InventoryItem

app = create_app()
with app.app_context():
    from sqlalchemy import text
    result = db.session.execute(text("SELECT branch, COUNT(*) as cnt FROM inventory_items GROUP BY branch")).fetchall()
    for row in result:
        print(f"branch={row[0]}: {row[1]} items")
