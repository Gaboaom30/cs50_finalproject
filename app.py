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

    # Print what you're returning
    data = [dict(row) for row in results]
    print("Returned JSON:", data)

    return jsonify(data)


if __name__ == "__main__":
    app.run(debug=True)


    

