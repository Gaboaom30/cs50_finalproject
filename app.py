import os
import datetime
import sqlite3

from flask import Flask, flash, redirect, render_template, request, session, g, jsonify
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash


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


@app.route("/")
def index():
    return render_template("layout.html")

@app.route("/inventory")
def inventory():
    db = get_db()
    inv = db.execute("SELECT * FROM inventory").fetchall()
    return render_template("inventory.html", inv=inv)

@app.route("/search_inventory")
def search_inventory():
    db = get_db()
    query = request.args.get("q", "").strip()
    results = db.execute(
        "SELECT * FROM inventory WHERE name LIKE ? OR id LIKE ?",
        (f"%{query}%", f"%{query}%")
    ).fetchall()
    data = [dict(row) for row in results]
    return jsonify(data)

@app.route("/register", methods=["GET", "POST"])
def register():
    
    if request.method == "POST":

        if "current_group_id" not in session:
            session["current_group_id"] = 0  # first time starting

        group_id = session["current_group_id"]

        typem = request.form.get("typem")
        if not typem:
            flash("Please select a type.")
            return redirect("/register")
        if typem not in ["sale", "purcharse", "return", "output"]:
            flash("Invalid type selected.")
            return redirect("/register")
        code = request.form.get("code")
        if not code:
            flash("Please enter a code.")
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

        if "pm_movements" not in session:
            session["pm_movements"] = []

        methods = request.form.getlist("payment_method[]")
        amounts = request.form.getlist("payment_amount[]")

        if methods and amounts:
            new_pm_movements = []
            total_amount = 0
            for method, amount in zip(methods, amounts):
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


if __name__ == "__main__":
    app.run(debug=True)


    

