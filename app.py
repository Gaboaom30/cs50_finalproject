import os
import datetime
import sqlite3
from flask import Flask, flash, redirect, render_template, request, session, g, jsonify, url_for
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps

# Configure application
app = Flask(__name__)
app.secret_key = "your_secret_key"

# --- Rutas persistentes con fallback automático ---
from pathlib import Path

def _writable_dir(preferred: str, fallback: str) -> str:
    """
    Devuelve 'preferred' si se puede crear/escribir ahí; si no, usa 'fallback'.
    """
    preferred_path = Path(preferred)
    fallback_path = Path(fallback)

    try:
        preferred_path.mkdir(parents=True, exist_ok=True)
        test_file = preferred_path / ".write_test"
        with open(test_file, "w") as f:
            f.write("ok")
        test_file.unlink(missing_ok=True)
        return str(preferred_path)
    except Exception:
        fallback_path.mkdir(parents=True, exist_ok=True)
        return str(fallback_path)

BASE_DIR = Path(__file__).parent

# Lo que queremos en producción (Render con disk montado en /var/data)
env_db_path = os.environ.get("DB_PATH", "/var/data/databases.db")
env_session_dir = os.environ.get("SESSION_FILE_DIR", "/var/data/flask-session")

# Si no es escribible, caemos a ./data dentro del proyecto (local)
DATA_DIR = _writable_dir(Path(env_db_path).parent, BASE_DIR / "data")
SESSION_DIR = _writable_dir(env_session_dir, BASE_DIR / "data" / "flask-session")

DB_PATH = os.environ.get("DB_PATH", str(Path(DATA_DIR) / "databases.db"))

import shutil

REPO_DB = os.path.join(os.path.dirname(__file__), "databases.db")

def _needs_seed(dst):
    return (not os.path.exists(dst)) or os.path.getsize(dst) == 0

if os.path.exists(REPO_DB) and _needs_seed(DB_PATH):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    shutil.copy2(REPO_DB, DB_PATH)
    print("SEED: Copiada DB del repo a", DB_PATH)


# Sessions en filesystem, guardadas en disco persistente (o ./data en local)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = SESSION_DIR
Session(app)

@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

def get_db():
    if "db" not in g:
        # Asegura la carpeta donde vive la DB (ya garantizado por _writable_dir, pero por las dudas)
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.route("/_debug/db")
def _debug_db():
    import os
    db = get_db()
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    users = None
    try:
        users = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    except Exception:
        users = "users table missing"
    return {
        "db_path": DB_PATH,
        "exists": os.path.exists(DB_PATH),
        "size_bytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0,
        "tables": [t["name"] for t in tables],
        "users_count": users
    }


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()

@app.before_request
def require_login():
    exempt_routes = ["login", "static", "_debug_db"]  # allow access to login and static files
    if "user_id" not in session and request.endpoint not in exempt_routes:
        return redirect(url_for("login"))

@app.get("/admin/download-db")
def download_db():
    token = request.args.get("token")
    if token != os.environ.get("ADMIN_TOKEN"):
        abort(403)
    return send_file(
        "/var/data/databases.db",  # e.g., /var/data/databases.db
        as_attachment=True,
        download_name="live_backup.db"
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user[2], password):
            session["user_id"] = user[0]
            session["username"] = user[1]
            return redirect("/")
        flash("Invalid username or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/", methods=["GET", "POST"])
def index():
    db = get_db()
    # Fetch credit sales and available payment methods
    rows = db.execute("""
        SELECT 
            inventory_movements.draft_id,
            inventory_movements.document_id AS document_id,
            inventory_movements.name AS name,
            inventory_movements.units AS units,
            currencies_movements.amount AS amount,
            currencies.name AS payment_method,
            inventory_movements.note AS note
        FROM inventory_movements
        JOIN currencies_movements  
            ON inventory_movements.document_id = currencies_movements.document_id
            AND inventory_movements.draft_id = currencies_movements.draft_id
        JOIN currencies 
            ON currencies.id = currencies_movements.payment_method_id
        WHERE inventory_movements.type = 'sale' AND currencies_movements.name = 'credit';
    """).fetchall()

    credit_by_doc = defaultdict(lambda: {"total": 0, "items": []})

    for row in rows:
        key = (row["document_id"], row["draft_id"])
        credit_by_doc[key]["total"] += row["amount"]
        credit_by_doc[key]["items"].append(row)

    cd = []
    for key, data in credit_by_doc.items():
        if data["total"] > 0 and data["items"]:
        # Usa la info del primer movimiento, pero con la suma como 'amount'
            first = dict(data["items"][0])
            first["amount"] = data["total"]
            cd.append(first)

    pm = db.execute("SELECT * FROM currencies").fetchall()

    delibery = db.execute("SELECT * FROM inventory_movements WHERE status = 'to deliver'").fetchall()

    return render_template("index.html", cd=cd, pm=pm, delivery=delibery)

@app.route("/inventory")
def inventory():
    db = get_db()
    inv = db.execute("SELECT * FROM inventory").fetchall()
    categories = sorted(set(item["category"] for item in inv))
    return render_template("inventory.html", categories=categories)

@app.route("/addProduct", methods=["POST"])
def addProduct():
    if request.method == "POST":
        db = get_db()
        code = request.form.get("product-code", "").strip()
        name = request.form.get("product-name", "").strip()
        price = request.form.get("product-price", "").strip()
        category = request.form.get("product-category", "").strip()
        quantity = 0  # Default quantity to 0 for new products

        if not code or not name or not price or not category:
            flash("All fields are required.")
            return redirect("/inventory")
        try:
            price = float(price)
        except ValueError:
            flash("Price must be a number.")
            return redirect("/inventory")
        if price < 0:
            flash("Price must be a positive number.")
            return redirect("/inventory")
        # Check if the product already exists
        existing_product = db.execute("SELECT * FROM inventory WHERE id = ?", (code,)).fetchone()
        if existing_product:
            flash("Product with this code already exists.")
            return redirect("/inventory")
        # Insert the new product
        db.execute("INSERT INTO inventory (id, name, price, category, quantity) VALUES (?, ?, ?, ?, ?)",
                   (code, name, price, category, quantity))
        db.commit()
        flash(f"Product '{name}' added successfully.")
        return redirect("/inventory")
    return redirect("/inventory")

@app.route("/editProduct", methods=["POST"])
def editProduct():
    if request.method == "POST":
        db = get_db()
        code = request.form.get("edit-id", "").strip()
        name = request.form.get("product-name", "").strip()
        price = request.form.get("product-price", "").strip()
        category = request.form.get("product-category", "").strip()

        print("DEBUG:", code, name, price, category)  # <- agrega esto

        if not code or not name or not price or not category:
            flash("All fields are required.")
            return redirect("/inventory")
        try:
            price = float(price)
        except ValueError:
            flash("Price must be a number.")
            return redirect("/inventory")
        if price < 0:
            flash("Price must be a positive number.")
            return redirect("/inventory")

        # Check if the product exists
        existing_product = db.execute("SELECT * FROM inventory WHERE id = ?", (code,)).fetchone()
        if not existing_product:
            flash("Product does not exist.")
            return redirect("/inventory")

        # Update the product
        db.execute("UPDATE inventory SET name = ?, price = ?, category = ? WHERE id = ?",
                   (name, price, category, code))
        db.commit()
        flash(f"Product '{name}' updated successfully.")
        return redirect("/inventory")
    return redirect("/inventory")

@app.route("/deleteProduct", methods=["POST"])
def deleteProduct():
    if request.method == "POST":
        db = get_db()
        code = request.form.get("delete-id", "").strip()

        if not code:
            flash("Product code cannot be empty.")
            return redirect("/inventory")

        # Check if the product exists
        existing_product = db.execute("SELECT * FROM inventory WHERE id = ?", (code,)).fetchone()
        if not existing_product:
            flash("Product does not exist.")
            return redirect("/inventory")

        # Check that the product quantity is 0
        if int(existing_product["quantity"]) != 0:
            flash("Product quantity must be 0 to delete.")
            return redirect("/inventory")

        # Delete the product
        db.execute("DELETE FROM inventory WHERE id = ?", (code,))
        db.commit()
        flash(f"Product with code '{code}' deleted successfully.")
        return redirect("/inventory")
    return redirect("/inventory")
    
@app.route("/currencies")
def currencies():
    db = get_db()
    currencies = db.execute("SELECT * FROM currencies").fetchall()
    currencies_movements = db.execute("SELECT * FROM currencies_movements").fetchall()
    return render_template("currencies.html", currencies=currencies, currencies_movements=currencies_movements)

@app.route("/addCurrency", methods=["POST"])
def addCurrency():
    if request.method == "POST":
        db = get_db()
        currency_name = request.form.get("currency").strip()
        if not currency_name:
            flash("Currency name cannot be empty.")
            return redirect("/currencies")
        
        # Check if the currency already exists
        existing_currency = db.execute("SELECT * FROM currencies WHERE name = ?", (currency_name,)).fetchone()
        if existing_currency:
            flash("Currency already exists.")
            return redirect("/currencies")

        # Insert the new currency
        db.execute("INSERT INTO currencies (name, balance) VALUES (?, 0)", (currency_name,))
        db.commit()
        flash(f"Currency '{currency_name}' added successfully.")
        return redirect("/currencies")
    return redirect("/currencies")

@app.route("/deleteCurrency", methods=["POST"])
def deleteCurrency():
    if request.method == "POST":
        db = get_db()
        currency_Id = request.form.get("currency").strip()
        if not currency_Id:
            flash("Currency ID cannot be empty.")
            return redirect("/currencies")

        # Check if the currency exists
        existing_currency = db.execute("SELECT * FROM currencies WHERE id = ?", (currency_Id,)).fetchone()
        if not existing_currency:
            flash("Currency does not exist.")
            return redirect("/currencies")

        # check that currency balance is 0
        if existing_currency["balance"] != 0:
            flash("Currency balance must be 0 to delete.")
            return redirect("/currencies")

        # Delete the currency
        db.execute("DELETE FROM currencies WHERE id = ?", (currency_Id,))
        db.commit()
        flash(f"Currency with ID '{currency_Id}' deleted successfully.")
        return redirect("/currencies")

@app.route("/currencies_movements")
def currencies_movements():
    db = get_db()
    page = int(request.args.get("page", 1))
    per_page = 20
    offset = (page - 1) * per_page
    # Get query parameters
    document_id = request.args.get("document_id", "").strip()
    draft_id = request.args.get("draft_id", "").strip()
    name_filter = request.args.get("currency", "").strip()
    id_filter = request.args.get("code", "").strip()
    date_filter = request.args.get("date", "").strip()
    start = request.args.get("start_date", "").strip()
    end = request.args.get("end_date", "").strip()
    typem = request.args.get("type", "").strip()

    sort_by = request.args.get("sort_by", "date")
    sort_dir = request.args.get("sort_dir", "asc")

    base_query = "SELECT * FROM currencies_movements WHERE name LIKE ?"
    total_query = "SELECT COUNT(*) as count FROM currencies_movements WHERE name LIKE ?"
    params = [f"%{name_filter}%"]

    if document_id:
        base_query += " AND document_id = ?"
        total_query += " AND document_id = ?"
        params.append(document_id)

    if typem:
        base_query += " AND type = ?"
        total_query += " AND type = ?"
        params.append(typem)
    
    if draft_id:
        base_query += " AND draft_id = ?"
        total_query += " AND draft_id = ?"
        params.append(draft_id)

    if id_filter:
        base_query += " AND id = ?"
        total_query += " AND id = ?"
        params.append(id_filter)   

    if date_filter == "today":
        today = datetime.now().date()
        base_query += " AND date(date) = ?"
        total_query += " AND date(date) = ?"
        params.append(str(today))

    elif date_filter == "this_week":

        today = datetime.now().date()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        base_query += " AND date(date) BETWEEN ? AND ?"
        total_query += " AND date(date) BETWEEN ? AND ?"
        params.append(str(start_of_week))
        params.append(str(end_of_week))

    elif date_filter == "this_month":
        today = datetime.now().date()
        start_of_month = today.replace(day=1)
        end_of_month = (start_of_month + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        base_query += " AND date(date) BETWEEN ? AND ?"
        total_query += " AND date(date) BETWEEN ? AND ?"
        params.append(str(start_of_month))
        params.append(str(end_of_month))

    elif date_filter == "custom":
        base_query += " AND date(date) BETWEEN ? AND ?"
        total_query += " AND date(date) BETWEEN ? AND ?"
        params.append(start)
        params.append(end)

    if sort_by in {"date", "document_id", "draft_id", "payment_method_id", "name", "amount"}:
        base_query += f" ORDER BY {sort_by} {sort_dir.upper()}"
        total_query += f" ORDER BY {sort_by} {sort_dir.upper()}"
    
    total_pages_query = db.execute(total_query, params).fetchall()
    total_count = total_pages_query[0]["count"]
    total_pages = (total_count + per_page - 1) // per_page

    base_query += " LIMIT ? OFFSET ?"
    params.append(per_page)
    params.append(offset)

    movements = db.execute(base_query, params).fetchall()
    data = [dict(row) for row in movements]
    return jsonify({
        "data": data,
        "total_pages": total_pages,
        "currentPage": page,
    })

@app.route("/inventory_movements")
def inventory_movements():
    db = get_db()
    movements = db.execute("SELECT * FROM inventory_movements ORDER BY date DESC").fetchall()
    return render_template("movements.html", movements=movements)

@app.route("/search_inventory_register")
def search_inventory_register():
    db = get_db()
    # Get query parameters
    query = request.args.get("q", "").strip()
  
    base_query = "SELECT * FROM inventory WHERE (Name LIKE ? OR Id LIKE ?)"
    params = [f"%{query}%", f"%{query}%"]

    results = db.execute(base_query, params).fetchall() 
    
    data = [dict(row) for row in results]

    return jsonify(data)

@app.route("/search_inventory")
def search_inventory():
    db = get_db()

    page = int(request.args.get("page", 1))
    per_page = 20
    offset = (page - 1) * per_page
    # Get query parameters
    query = request.args.get("q", "").strip()
    categories = request.args.get("category", "").strip()

    sort_by = request.args.get("sort_by")
    sort_dir = request.args.get("sort_dir", "asc")   

    print("DEBUG:", sort_by, sort_dir)  # <- agrega esto
   
    base_query = "SELECT * FROM inventory WHERE (Name LIKE ? OR Id LIKE ?)"
    total_query = "SELECT COUNT(*) as count FROM inventory WHERE (Name LIKE ? OR Id LIKE ?)"
    params = [f"%{query}%", f"%{query}%"]

    if categories:
        base_query += " AND category = ?"
        total_query += " AND category = ?"
        params.append(categories)

    total_pages_query = db.execute(total_query, params).fetchall()
    total_count = total_pages_query[0]["count"]
    total_pages = (total_count + per_page - 1) // per_page

    if sort_by in {"Name", "Id", "Price", "Quantity"}:
        base_query += f" ORDER BY {sort_by} {sort_dir.upper()}"


    base_query += " LIMIT ? OFFSET ?"
    params.append(per_page)
    params.append(offset)

    results = db.execute(base_query, params).fetchall() 
    
    data = [dict(row) for row in results]

    return jsonify({
        "data": data,
        "total_pages": total_pages,
        "current_page": page,
        })

@app.route("/search_inventory_movements")
def search_inventory_movements():
    db = get_db()

    page = int(request.args.get("page", 1))
    per_page = 20
    offset = (page - 1) * per_page
    # Get query parameters
    query = request.args.get("q", "").strip()
    type_filter = request.args.get("type", "").strip()
    status_filter = request.args.get("status", "").strip()
    date_filter = request.args.get("date", "").strip()
    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()
    document_id = request.args.get("document_id", "").strip()

    sort_by = request.args.get("sort_by")
    sort_dir = request.args.get("sort_dir", "asc")

    print("DEBUG:", document_id)  # <- agrega esto

    base_query = "SELECT * FROM inventory_movements WHERE (name LIKE ? OR product_id LIKE ?)"
    params = [f"%{query}%", f"%{query}%"]

    total_query = "SELECT COUNT(*) as count FROM inventory_movements WHERE (name LIKE ? OR product_id LIKE ?)"  

    if type_filter:
        base_query += " AND type = ?"
        total_query += " AND type = ?"
        params.append(type_filter)

    if status_filter:
        base_query += " AND status = ?"
        total_query += " AND status = ?"
        params.append(status_filter)
    
    if document_id:
        base_query += " AND document_id = ?"
        total_query += " AND document_id = ?"
        params.append(document_id)

    if date_filter == "today":
        today = datetime.now().date()
        base_query += " AND date(date) = ?"
        total_query += " AND date(date) = ?"
        params.append(str(today))

    elif date_filter == "this_week":
        today = datetime.now().date()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=6)
        base_query += " AND date(date) BETWEEN ? AND ?"
        total_query += " AND date(date) BETWEEN ? AND ?"
        params.append(str(start_of_week))
        params.append(str(end_of_week))

    elif date_filter == "this_month":
        today = datetime.now().date()
        start_of_month = today.replace(day=1)
        end_of_month = (start_of_month + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        base_query += " AND date(date) BETWEEN ? AND ?"
        total_query += " AND date(date) BETWEEN ? AND ?"
        params.append(str(start_of_month))
        params.append(str(end_of_month))

    elif date_filter == "custom":
        base_query += " AND date(date) BETWEEN ? AND ?"
        total_query += " AND date(date) BETWEEN ? AND ?"
        params.append(start)
        params.append(end)

    
    total_pages_query = db.execute(total_query, params).fetchall()
    total_count = total_pages_query[0]["count"]
    total_pages = (total_count + per_page - 1) // per_page
    print("DEBUG total_count:", total_pages)  # <- agrega esto
    
    if sort_by in {"date", "name", "document_id", "draft_id", "product_id", "status"}:
        base_query += f" ORDER BY {sort_by} {sort_dir.upper()}"

    base_query += f" LIMIT ? OFFSET ?"
    params.append(per_page)
    params.append(offset)

    results = db.execute(base_query, params).fetchall() 
    data = [dict(row) for row in results]

    print("DEBUG total_pages:", total_pages)
    
    return jsonify({
        "data": data,
        "total_pages": total_pages,
        "current_page": page,
        })

@app.route("/delivery", methods=["POST"])
def delivery():
    if request.method == "POST":
        db = get_db()
        draft_id = request.form.get("draft_id")
        movement_id = request.form.get("movement_id")
        if not draft_id or not movement_id:
            flash("Draft ID and Movement ID are required.")
            return redirect("/")
        
        # Update the status of the movement to 'delivered'
        db.execute(
            "UPDATE inventory_movements SET status = 'delivered' WHERE draft_id = ? AND document_id = ?",
            (draft_id, movement_id)
        )
        db.commit()
        flash("Delivery status updated successfully.")
        return redirect("/")

@app.route("/index_payment", methods=["POST"])
def index_payment():
    # Handle payment form submission
    if request.method == "POST":
        db = get_db()
        movement_id = request.form.get("movement_id")
        draft_id = request.form.get("draft_id")
        topay = request.form.get("amount")
        # Fetch the total amount for this movement
    
        if not topay:
            flash("Amount not provided.")
            return redirect("/")

        try:
            total = float(topay)
        except ValueError:
            flash("Invalid amount.")
            return redirect("/")

        methods = request.form.getlist("payment_method[]")
        amounts = request.form.getlist("payment_amount[]")

        total_amount = 0
        new_pm_movements = []

        if methods and amounts and len(methods) == len(amounts):
            for method, amount in zip(methods, amounts):
                new_pm_movements.append({
                    "method": method,
                    "amount": float(amount)
                })
                total_amount += float(amount)

            if total_amount > total:
                flash("Total payment exceeds the movement total.")
                return redirect("/")

            # Optionally: store in session for review
            if "pm_movements" not in session:
                session["pm_movements"] = []

            session["pm_movements"].extend(new_pm_movements)

            
            for payment in new_pm_movements:
                payment_method_id = db.execute("SELECT id FROM currencies WHERE name = ?", (payment["method"],)).fetchone()
                
                if payment_method_id:
                    payment_method_id = payment_method_id[0]
                else:
                    flash("Payment method not found.")
                    return redirect("/")

                db.execute("INSERT INTO currencies_movements (name, amount, draft_id, date, document_id, payment_method_id, type) VALUES (?, -?, ?, ?, ?, ?, ?)",
                    ("credit", payment["amount"],
                    draft_id, datetime.now(), movement_id, payment_method_id, "expense")
                )

                db.execute(
                    "INSERT INTO currencies_movements (name, amount, draft_id, date, document_id, payment_method_id, type) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (payment["method"], payment["amount"],
                    draft_id, datetime.now(), movement_id, payment_method_id, "income")
                )

                # Update the balance
                db.execute(
                    "UPDATE currencies SET balance = balance + ? WHERE name = ?",
                    (payment["amount"], payment["method"])
                )
                
                db.execute("UPDATE currencies SET balance = balance - ? WHERE name = 'credit'", (payment["amount"],))
            db.commit()

            session.pop("pm_movements", None)  # Clear the session after processing

            flash("Payment registered successfully.")
            return redirect("/")
        else:
            flash("Missing or invalid payment data.")
            return redirect("/")

@app.route("/register", methods=["GET", "POST"])
def register():
    
    if request.method == "POST":

        db = get_db()

        if "current_group_id" not in session:
            session["current_group_id"] = 0  # first time starting

        group_id = session["current_group_id"]

        typem = request.form.get("typem")
        if not typem:
            flash("Please select a type.")
            return redirect("/register")
        if typem not in ["sale", "purchase", "return", "output"]:
            flash("Invalid type selected.")
            return redirect("/register")
        code = request.form.get("code")
        if not code:
            flash("Please enter a code.")
            return redirect("/register")

        
        check_0 = db.execute("SELECT quantity FROM inventory WHERE id = ?", (code,)).fetchone()
        if check_0 is None or check_0[0] < 1:
            flash("Product not found or out of stock.")
            return redirect("/register")

        name = request.form.get("search_name")
        if not name:
            flash("Please enter a name.")
            return redirect("/register")
        
        qty = request.form.get("qty")
        if not qty:
            flash("Please enter a quantity.")
            return redirect("/register")
        try:
            qty = int(qty)
        except ValueError:
            flash("Quantity must be a number.")
            return redirect("/register")
        if qty < 0:
            flash("Quantity must be a positive number.")
            return redirect("/register")
        
        
        price = request.form.get("price")
        if not price:
            flash("Please enter a price.")
            return redirect("/register")
        try:
            price = float(price)
        except ValueError:
            flash("Price must be a number.")
            return redirect("/register")
        if price < 0:
            flash("Price must be a positive number.")
            return redirect("/register")
        status = request.form.get("status")
        if not status:
            flash("Please select a status.")
            return redirect("/register")
        if status not in ["delivered", "to deliver"]:
            flash("Invalid status selected.")
            return redirect("/register")
        note = request.form.get("note")
        total = price * qty

        if typem == "purchase" or typem == "return":
            total = -(total)
        

        if "pm_movements" not in session:
            session["pm_movements"] = []

        methods = request.form.getlist("payment_method[]")
        amounts = request.form.getlist("payment_amount[]")

        if methods and amounts:
            new_pm_movements = []
            total_amount = 0
            for method, amount in zip(methods, amounts):

                if not method or not amount:
                    flash("Please provide both payment method and amount.")
                    return redirect("/register")
                try:
                    amount = float(amount)
                except ValueError:
                    flash("Invalid amount provided.")
                    return redirect("/register")
                if amount < 0:
                    flash("Amount must be a positive number.")
                    return redirect("/register")
                if amount > total:
                    flash("Payment amount cannot exceed the total price.")
                    return redirect("/register")
                
                new_pm_movements.append({
                    "pm_id": group_id,
                    "method": method,
                    "amount": float(amount)
                })
                total_amount += float(amount)

            if abs(total_amount - total) > 0.01:
                flash("Total amount does not match the total price.")
                return redirect("/register")
            
            session["pm_movements"].extend(new_pm_movements)
            
        else:
        # fallback to single pm
            pm = request.form.get("pm")

            if not pm:
                flash("Please select a payment method.")
                return redirect("/register")

            session["pm_movements"].append({
                "pm_id": group_id,
                "method": pm,
                "amount": total
            })

        movement ={
            "typem": typem,
            "code": code,
            "name": name,
            "qty": qty,
            "price": price,
            "total": total,
            "note": note,
            "status": status,
            "pm_id": group_id
        }

        if "draft_movements" not in session:
            session["draft_movements"] = []

        draft = session["draft_movements"]
        draft.append(movement)
        session["draft_movements"] = draft
        print("Current draft_movements:", session.get("draft_movements"))
        
        session["current_group_id"] += 1
        session.modified = True
        
        return redirect("/register")
    
    else:
        db = get_db()
        pm = db.execute("SELECT name FROM currencies").fetchall()

        grouped_pm = {}
        if "pm_movements" in session:
            for payment in session["pm_movements"]:
                method = payment["method"]
                amount = payment["amount"]
                if method in grouped_pm:
                    grouped_pm[method] += amount
                else:
                    grouped_pm[method] = amount


        return render_template("register.html", pm=pm, grouped_pm=grouped_pm)

@app.route("/register_inventoryM", methods=["POST"])
def register_inventoryM():
    if request.method == "POST":
        db = get_db()

        if "current_group_id" not in session:
            session["current_group_id"] = 0  # first time starting
        group_id = session["current_group_id"]

        typem = request.form.get("typem")
        if not typem:
            flash("Please select a type.")
            return redirect("/register")

        if typem not in ["output", "input"]:
            flash("Invalid type selected.")
            return redirect("/register")
        
        code = request.form.get("code")
        if not code:
            flash("Please enter a code.")

        checkName = db.execute("SELECT Name FROM inventory WHERE Id = ?", (code,)).fetchone()        
        if checkName is None:
            flash("Product not found.")
            return redirect("/register")

        name = request.form.get("search_name")
        if not name:
            flash("Please enter a name.")
            return redirect("/register")

        checkCode = db.execute("SELECT Id FROM inventory WHERE name = ?", (name,)).fetchone()
        if checkCode is None:
            flash("Product not found.")
            return redirect("/register")

        if name != checkName["Name"]:
            flash("Product name does not match the code.")
            return redirect("/register")

        if code != checkCode["Id"]:
            flash("Product code does not match the name.")
            return redirect("/register")

        qty = request.form.get("qty")
        if not qty:
            flash("Please enter a quantity.")
            return redirect("/register")
        try:
            qty = int(qty)
        except ValueError:
            flash("Quantity must be a number.")
            return redirect("/register")
        if qty < 0:
            flash("Quantity must be a positive number.")
            return redirect("/register")

        price = 0

        if typem == "output":
            qty = -qty  # Negate quantity for output movements

        check_0 = db.execute("SELECT quantity FROM inventory WHERE id = ?", (code,)).fetchone()
        if check_0 is None or check_0[0] + qty < 1:
            flash("Product not found or out of stock.")
            return redirect("/register")

        note = request.form.get("note")
        total = 0

        status = request.form.get("status")
        if not status:
            flash("Please select a status.")
            return redirect("/register")
        if status not in ["delivered", "to deliver"]:
            flash("Invalid status selected.")
            return redirect("/register")

        inventoryM = {
            "typem": typem,
            "code": code,
            "name": name,
            "qty": qty,
            "price": price,
            "total": total,
            "note": note,
            "status": status,
            "pm_id": group_id
        }

        if "draft_inventoryM" not in session:
            session["draft_inventoryM"] = []

        draft = session["draft_inventoryM"]
        draft.append(inventoryM)
        session["draft_inventoryM"] = draft
        session["current_group_id"] += 1
        session.modified = True

        return redirect("/register")

@app.route("/register_currencyM", methods=["POST"])
def register_currencyM():
    if request.method == "POST":
        db = get_db()

        if "current_group_id" not in session:
            session["current_group_id"] = 0  # first time starting
        group_id = session["current_group_id"]
        typem = request.form.get("typem")
        if not typem:
            flash("Please select a type.")
            return redirect("/register")

        if typem not in ["income", "expense"]:
            flash("Invalid type selected.")
            return redirect("/register")

        pm = request.form.get("pm")
        if not pm:
            flash("Please select a payment method.")
            return redirect("/register")
        
        amount = request.form.get("price")
        if not amount:
            flash("Please enter an amount.")
            return redirect("/register")
        try:
            amount = float(amount)
        except ValueError:
            flash("Amount must be a number.")
            return redirect("/register")
        if amount < 0:
            flash("Amount must be a positive number.")
            return redirect("/register")

        note = request.form.get("note")
        
        if typem == "expense":
            amount = -amount

        currencyM = {
            "typem": typem,
            "pm": pm,
            "amount": amount,
            "note": note,
            "pm_id": group_id
        }

        if "draft_currencyM" not in session:
            session["draft_currencyM"] = []
        draft = session["draft_currencyM"]
        draft.append(currencyM)
        session["draft_currencyM"] = draft
        session["current_group_id"] += 1
        session.modified = True
        return redirect("/register")
        
@app.route("/get_product_by_code")
def get_product_by_code():
    code = request.args.get("code")
    if not code:
        return jsonify({})
    db = get_db()
    product = db.execute("SELECT Name, Price FROM inventory WHERE Id = ?", (code,)).fetchone()
    if product:
        return jsonify(dict(product))
    return jsonify({})

@app.route("/delete_movement", methods=["POST"])
def delete_movement():
    index = int(request.form.get("index"))

    if "draft_movements" in session:
        drafts = session["draft_movements"]

        if 0 <= index < len(drafts):
            # Get the pm_id before popping
            pm_id_to_delete = drafts[index]["pm_id"]

            # Remove the movement
            drafts.pop(index)
            session["draft_movements"] = drafts

            # Also remove related payment methods
            if "pm_movements" in session:
                payments = session["pm_movements"]
                # Keep only payments not matching the pm_id
                payments = [payment for payment in payments if payment["pm_id"] != pm_id_to_delete]
                session["pm_movements"] = payments

            flash("Movement and related payments deleted.")
        else:
            flash("Invalid movement index.")

    return redirect("/register")

@app.route("/delete_inventoryM", methods=["POST"])
def delete_inventoryM():
    index = int(request.form.get("index"))

    if "draft_inventoryM" in session:
        drafts = session["draft_inventoryM"]

        if 0 <= index < len(drafts):
            # Get the pm_id before popping
            pm_id_to_delete = drafts[index]["pm_id"]

            # Remove the movement
            drafts.pop(index)
            session["draft_inventoryM"] = drafts

            flash("Movement and related payments deleted.")
        else:
            flash("Invalid movement index.")

    return redirect("/register")

@app.route("/delete_currencyM", methods=["POST"])
def delete_currencyM():
    index = int(request.form.get("index"))

    if "draft_currencyM" in session:
        drafts = session["draft_currencyM"]

        if 0 <= index < len(drafts):
            # Get the pm_id before popping
            pm_id_to_delete = drafts[index]["pm_id"]

            # Remove the movement
            drafts.pop(index)
            session["draft_currencyM"] = drafts
        
            flash("Movement and related payments deleted.")    
        else:
            flash("Invalid movement index.")

    return redirect("/register")

@app.route("/clear_drafts")
def clear_drafts():
    session.pop("draft_movements", None)
    session.pop("pm_movements", None)
    flash("Drafts cleared!")
    return redirect("/register")

@app.route("/confirm", methods=["POST"])
def confirm():

    drafts = session.get("draft_movements", [])
    pm_movements = session.get("pm_movements", [])
    draft_currencyM = session.get("draft_currencyM", [])
    draft_inventoryM = session.get("draft_inventoryM", [])

    if not drafts and not draft_currencyM and not draft_inventoryM:
        flash("No movements to confirm.")
        return redirect("/register")

    db = get_db()
    last_doc = db.execute("SELECT MAX(document_id) FROM inventory_movements").fetchone()
    document_id = (last_doc[0] or 0) + 1

    for movement in drafts:
        operation = 1
        if movement["typem"] in ["sale", "output"]:
            operation = -1

        qty = db.execute("SELECT Quantity FROM inventory WHERE id = ?", (movement["code"],)).fetchone()
        if (qty[0] + (operation * movement["qty"])) < 0:
            flash(f"Not enough stock for product {movement['name']} (Code: {movement['code']}).")
            return redirect("/register")

        db.execute(
            "INSERT INTO inventory_movements (type, name, product_id, units, price, toal, note, status, draft_id, date, document_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (movement["typem"], movement["name"], movement["code"],
            operation * movement["qty"], movement["price"], movement["total"],
            movement["note"], movement["status"],
            movement["pm_id"], datetime.now(),
            document_id)
        )
            
        db.execute(
            "UPDATE inventory SET Quantity = Quantity + ? WHERE id = ?",
            (operation * movement["qty"], movement["code"])
        )
                
    for payment in pm_movements:
        payment_method_id = db.execute("SELECT id FROM currencies WHERE name = ?", (payment["method"],)).fetchone()
            
        if payment_method_id:
            payment_method_id = payment_method_id[0]
        else:
            flash("Payment method not found.")
            return redirect("/register")
                
        # Find the matching movement by pm_id
        related_movement = next((m for m in drafts if m["pm_id"] == payment["pm_id"]), None)

        if not related_movement:
            flash("Could not find related movement for payment.")
            return redirect("/register")

        movement_type = related_movement["typem"]

        # Apply the correct logic based on movement type
        operation = 1
        typem = "income"
        if movement_type in ["pucharse", "return"]:
            operation = -1
            typem = "expense"
        db.execute(
            "UPDATE currencies SET balance = balance + ? WHERE name = ?",
            (operation * payment["amount"], payment["method"])
        )

        db.execute(
            "INSERT INTO currencies_movements (name, amount, draft_id, date, document_id, payment_method_id, type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (payment["method"], payment["amount"],
            payment["pm_id"], datetime.now(), document_id, payment_method_id, typem)
        )
            

    for movement in draft_currencyM:
        currencyM_id = db.execute("SELECT id FROM currencies WHERE name = ?", (movement["pm"],)).fetchone()
        amount = movement["amount"]

        balance = db.execute("SELECT balance FROM currencies WHERE name = ?", (movement["pm"],)).fetchone()
        if (balance[0] + amount) < 1:
            flash(f"Not enough amount for {movement["pm"]}")
            return redirect("/register")

        db.execute(
            "INSERT into currencies_movements (name, amount, draft_id, date, document_id, payment_method_id, note, type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (movement["pm"], amount, movement["pm_id"], datetime.now(), document_id, currencyM_id[0], movement["note"], movement["typem"])
        )

        db.execute("UPDATE currencies SET balance = balance + ? WHERE id = ?",
            (amount, currencyM_id[0])
        )
        
    for movement in draft_inventoryM:
        qty = db.execute("SELECT Quantity FROM inventory WHERE Id = ?", (movement["code"],)).fetchone()
        amount = movement["qty"]
            
        if (qty[0] + amount) < 1:
            flash(f"Product {movement["name"]} is out of stock")
            return redirect("/register")
            
        db.execute("""
            INSERT INTO inventory_movements 
            (product_id, type, units, date, note, document_id, draft_id, name, price, toal, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            movement["code"], movement["typem"], movement["qty"],
            datetime.now(), movement["note"], document_id,
            movement["pm_id"], movement["name"], movement["price"], movement["total"], movement["status"]
        ))

        db.execute("UPDATE inventory SET Quantity = Quantity + ? WHERE Id = ?",
            (movement["qty"], movement["code"])
        )
                
    db.commit()
    session.pop("draft_movements", None)
    session.pop("pm_movements", None)
    session.pop("draft_currencyM", None)
    session.pop("draft_inventoryM", None)
    session.pop("current_group_id", None)
    flash("Movements confirmed!")
    
    return redirect("/register")

if __name__ == "__main__":
    app.run(debug=True)


    

