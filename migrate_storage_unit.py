"""
One-time migration: adds the `storage_unit` column to inventory_items.
Run this once: python migrate_storage_unit.py
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), 'tricoffee.db')

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Check if column already exists
cur.execute("PRAGMA table_info(inventory_items)")
cols = [row[1] for row in cur.fetchall()]

if 'storage_unit' not in cols:
    cur.execute("ALTER TABLE inventory_items ADD COLUMN storage_unit VARCHAR(20) DEFAULT 'pcs'")
    conn.commit()
    print("✅  Column 'storage_unit' added to inventory_items.")
else:
    print("ℹ️  Column 'storage_unit' already exists — nothing to do.")

conn.close()
