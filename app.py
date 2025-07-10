import os
import datetime
import sqlite3

from flask import Flask, flash, redirect, render_template, request, session, g, jsonify
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
from collections import defaultdict

# Configure application
app = Flask(__name__)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
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
        g.db = sqlite3.connect("databases.db")
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


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

    # Step 3: Filter only those with credit still pending
    cd = []
    for data in credit_by_doc.values():
        if data["total"] > 0:
            cd.extend(data["items"])

    pm = db.execute("SELECT * FROM currencies").fetchall()

    delibery = db.execute("SELECT * FROM inventory_movements WHERE status = 'to deliver'").fetchall()

    return render_template("index.html", cd=cd, pm=pm, delivery=delibery)

@app.route("/inventory")
def inventory():
    db = get_db()
    inv = db.execute("SELECT * FROM inventory").fetchall()
    categories = sorted(set(item["category"] for item in inv))
    return render_template("inventory.html", categories=categories)

@app.route("/currencies")
def currencies():
    db = get_db()
    currencies = db.execute("SELECT * FROM currencies").fetchall()
    currencies_movements = db.execute("SELECT * FROM currencies_movements").fetchall()
    return render_template("currencies.html", currencies=currencies, currencies_movements=currencies_movements)

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

    sort_by = request.args.get("sort_by", "date")
    sort_dir = request.args.get("sort_dir", "asc")

    base_query = "SELECT * FROM currencies_movements WHERE name LIKE ?"
    total_query = "SELECT COUNT(*) as count FROM currencies_movements WHERE name LIKE ?"
    params = [f"%{name_filter}%"]

    if document_id:
        base_query += " AND document_id = ?"
        total_query += " AND document_id = ?"
        params.append(document_id)
    
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

                db.execute("INSERT INTO currencies_movements (name, amount, draft_id, date, document_id, payment_method_id) VALUES (?, -?, ?, ?, ?, ?)",
                    ("credit", payment["amount"],
                    draft_id, datetime.now(), movement_id, payment_method_id)
                )

                db.execute(
                    "INSERT INTO currencies_movements (name, amount, draft_id, date, document_id, payment_method_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (payment["method"], payment["amount"],
                    draft_id, datetime.now(), movement_id, payment_method_id)
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


@app.route("/clear_drafts")
def clear_drafts():
    session.pop("draft_movements", None)
    session.pop("pm_movements", None)
    flash("Drafts cleared!")
    return redirect("/register")

@app.route("/confirm", methods=["POST"])
def confirm():
    if "draft_movements" not in session or not session["draft_movements"]:
        flash("No movements to confirm.")
        return redirect("/register")

    db = get_db()
    drafts = session["draft_movements"]
    pm_movements = session.get("pm_movements", [])

    last_doc = db.execute("SELECT MAX(document_id) FROM inventory_movements").fetchone()[0]
    if last_doc is None:
        document_id = 1
    else:
        document_id = last_doc + 1

    for movement in drafts:
        qty = db.execute("SELECT Quantity FROM inventory WHERE id = ?", (movement["code"],)).fetchone()
        if qty is None or qty[0] < movement["qty"]:
            flash(f"Not enough stock for product {movement['name']} (Code: {movement['code']}).")
            return redirect("/register")
        db.execute(
            "INSERT INTO inventory_movements (type, name, product_id, units, price, toal, note, status, draft_id, date, document_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (movement["typem"], movement["name"], movement["code"],
            movement["qty"], movement["price"], movement["total"],
            movement["note"], movement["status"],
            movement["pm_id"], datetime.now(),
            document_id)
        )
        operation = -1
        if movement["typem"] in ["purchase", "return"]:
            operation = 1
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
       
        db.execute(
            "INSERT INTO currencies_movements (name, amount, draft_id, date, document_id, payment_method_id) VALUES (?, ?, ?, ?, ?, ?)",
            (payment["method"], payment["amount"],
            payment["pm_id"], datetime.now(), document_id, payment_method_id)
        )
            
            
        # Find the matching movement by pm_id
        related_movement = next((m for m in drafts if m["pm_id"] == payment["pm_id"]), None)

        if not related_movement:
            flash("Could not find related movement for payment.")
            return redirect("/register")

        movement_type = related_movement["typem"]

        # Apply the correct logic based on movement type
        operation = 1
        if movement_type in ["pucharse", "return"]:
            operation = -1
        db.execute(
            "UPDATE currencies SET balance = balance + ? WHERE name = ?",
            (operation * payment["amount"], payment["method"])
        )

    db.commit()
    session.pop("draft_movements", None)
    session.pop("pm_movements", None)
    session.pop("current_group_id", None)
    flash("Movements confirmed!")
    
    return redirect("/register")

if __name__ == "__main__":
    app.run(debug=True)


    

