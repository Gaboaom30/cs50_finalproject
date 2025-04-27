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

        pm = request.form.get("pm")
        if not pm:
            flash("Please select a payment method.")
            return redirect("/register")

        total = price * qty

        movement ={
            "typem": typem,
            "code": code,
            "name": name,
            "qty": qty,

            "price": price,
            "total": total,
            "note": note,
            "status": status,
            "pm": pm
        }

        if "draft_movements" not in session:
            session["draft_movements"] = []

        draft = session["draft_movements"]
        draft.append(movement)
        session["draft_movements"] = draft
        print("Current draft_movements:", session.get("draft_movements"))

     
        return redirect("/register")
    else:
        db = get_db()
        pm = db.execute("SELECT name FROM currencies").fetchall()
        return render_template("register.html", pm=pm)

@app.route("/delete_movement", methods=["POST"])
def delete_movement():
    index = int(request.form.get("index"))

    if "draft_movements" in session:
        drafts = session["draft_movements"]

        if 0 <= index < len(drafts):
            drafts.pop(index)
            session["draft_movements"] = drafts  # reassign to trigger update
            flash("Movement deleted.")
        else:
            flash("Invalid movement index.")

    return redirect("/register")

if __name__ == "__main__":
    app.run(debug=True)


    

