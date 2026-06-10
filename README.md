# ☕ TRICOFFEE — Inventory Management System

A modern, full-featured coffee shop inventory management web application built with **Flask + SQLite**.

---

## Tech Stack

| Layer       | Technology |
|-------------|------------|
| Backend     | Python 3.10+ · Flask 3 · Flask-SQLAlchemy · Flask-Login |
| Database    | SQLite (file: `tricoffee.db`) |
| Frontend    | Bootstrap 5.3 · Chart.js 4 · Font Awesome 6 |
| Reports     | ReportLab (PDF) · openpyxl (Excel) |

---

## Project Structure

```
tricoffee/
├── app.py              # App factory + seeding
├── models.py           # SQLAlchemy models
├── utils.py            # Decorators & helpers
├── tricoffee.db        # SQLite database (auto-created)
├── requirements.txt
├── routes/
│   ├── auth.py         # Login / Logout
│   ├── dashboard.py    # Admin dashboard
│   ├── inventory.py    # Full CRUD + stock-in
│   ├── admin.py        # User management + logs
│   ├── staff.py        # Transfer + stock-out
│   └── reports.py      # Daily/Weekly/Monthly + export
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── inventory/      # list, add, edit, transactions, categories,
│   │                   #   main_storage, area_storage, stock_in
│   ├── admin/          # users, add_user, edit_user, logs
│   ├── staff/          # dashboard, transfer, stock_out, my_transactions
│   └── reports/        # index
└── static/
    ├── css/style.css
    └── js/main.js
```

---

## Quick Start

### 1. Clone / extract the project

```bash
cd tricoffee
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the app

```bash
python app.py
```

Open your browser at **http://127.0.0.1:5000**

The SQLite database (`tricoffee.db`) and all tables are created automatically on first run.

---

## Default Login Credentials

| Role  | Username | Password  |
|-------|----------|-----------|
| Admin | `admin`  | `admin123` |
| Staff | `staff`  | `staff123` |

> **Change these immediately** in Admin → Users after first login.

---

## Two User Roles

### 🔑 Admin
- Full dashboard with charts (stock status, category breakdown, 7-day trend)
- Complete inventory CRUD — add / edit / delete items and categories
- **Main Storage** management — receive stock from suppliers
- **Area Storage** overview
- Adjust stock quantities (main or area) manually
- All transactions log with filters
- Reports: Daily / Weekly / Monthly — export to **PDF** or **Excel**
- User management (add / edit / deactivate / delete users)
- Activity Logs (full audit trail with IP, timestamp, action)

### 👤 Staff
- Personal dashboard with low-stock alerts and recent activity
- **Area Storage** view (read-only stock levels + status)
- **Stock In (Transfer)** — move items from Main → Area storage
- **Stock Out (Use)** — deduct items used from Area storage
- My Transactions — personal history

---

## Inventory Categories (pre-seeded)

| Category | Items | Unit |
|----------|-------|------|
| Coffee Ingredients | 33 items | g/ml |
| Packaging Supplies | 13 items | pcs |
| Pastries | (staff adds dynamically) | custom |

---

## Stock Flow

```
Supplier
   │
   ▼  Admin: Stock In (Supplier)
Main Storage
   │
   ▼  Staff/Admin: Transfer to Area
Area Storage
   │
   ▼  Staff/Admin: Stock Out (Used)
Consumed
```

---

## Reports

Navigate to **Reports** and choose Daily / Weekly / Monthly.

- **Export Excel** → downloads `.xlsx` with summary + full transaction list
- **Export PDF**   → downloads landscape A4 `.pdf` with styled tables
- **Print**        → browser print (sidebar/buttons hidden automatically)

---

## Notes

- The SQLite database file is `tricoffee.db` in the project root.
- No external database server needed — runs anywhere Python runs.
- To reset data: delete `tricoffee.db` and restart the app.
