"""
Run once to fix the database:
  - Sets all items with NULL/0 branch to branch=1
  - Seeds branch 1 items if they're missing
  - Sets storage_unit to 'pcs' for all items

Usage: python fix_db.py
"""
import sqlite3, os

DB = os.path.join(os.path.dirname(__file__), 'tricoffee.db')
conn = sqlite3.connect(DB)

# Fix branch values
conn.execute("UPDATE inventory_items SET branch = 1 WHERE branch IS NULL OR branch = 0")
conn.execute("UPDATE inventory_items SET storage_unit = 'pcs' WHERE storage_unit IS NULL OR storage_unit = ''")
conn.execute("UPDATE users SET branch = 0 WHERE role = 'admin'")
conn.commit()

# Check if branch 1 is still empty
count = conn.execute("SELECT COUNT(*) FROM inventory_items WHERE branch = 1").fetchone()[0]
print(f"Branch 1 items after fix: {count}")

if count == 0:
    print("Branch 1 still empty — seeding via app...")
    conn.close()
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from app import create_app
    app = create_app()  # _seed_branch1_if_missing runs automatically
else:
    conn.close()
    print("Done. Branch 1 is populated.")

import sqlite3
conn = sqlite3.connect(DB)
for row in conn.execute("SELECT branch, COUNT(*) FROM inventory_items GROUP BY branch"):
    print(f"  branch={row[0]}: {row[1]} items")
conn.close()
