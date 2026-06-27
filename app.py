import sqlite3
import os
from flask import Flask, render_template, request, redirect, url_for, flash, g
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "..", "jokatech_business.db")
app = Flask(__name__)
app.secret_key = "change-this-secret-key"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db:
        db.close()


class User(UserMixin):
    def __init__(self, row):
        self.id = str(row["id"])
        self.email = row["email"]
        self.name = row["name"]
        self.is_admin = row["is_admin"] if "is_admin" in row.keys() else "No"


@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM clients WHERE id = ?", (user_id,)).fetchone()
    return User(row) if row else None

def is_admin_user():
    return (
        current_user.is_authenticated
        and getattr(current_user, "is_admin", "No") == "Yes"
    )

def setup_tables():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password_hash TEXT,
            payment_status TEXT DEFAULT 'Unpaid'
        )
    """)
    try:
        db.execute("ALTER TABLE clients ADD COLUMN is_admin TEXT DEFAULT 'No'")
    except sqlite3.OperationalError:
        pass
    db.execute("""
        CREATE TABLE IF NOT EXISTS trainings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            video_url TEXT,
            price TEXT,
            active TEXT DEFAULT 'Yes'
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            training_id INTEGER,
            access_granted TEXT DEFAULT 'No'
        )
    """)
    
    db.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        subject TEXT,
        category TEXT,
        priority TEXT,
        status TEXT DEFAULT 'Open',
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    db.execute("""
    CREATE TABLE IF NOT EXISTS ticket_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER,
        sender_type TEXT,
        message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    db.commit()


@app.before_request
def before_request():
    setup_tables()


@app.route("/")
def home():
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        db = get_db()
        try:
            db.execute(
                "INSERT INTO clients (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password))
            )
            db.commit()
            flash("Account created. You can log in now.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That email already exists.")

    return render_template("login.html", register=True)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        db = get_db()
        row = db.execute("SELECT * FROM clients WHERE email = ?", (email,)).fetchone()

        if row and check_password_hash(row["password_hash"], password):
            login_user(User(row))
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.")

    return render_template("login.html", register=False)


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/trainings")
@login_required
def trainings():
    db = get_db()

    rows = db.execute("""
        SELECT trainings.*
        FROM trainings
        JOIN enrollments ON trainings.id = enrollments.training_id
        WHERE enrollments.client_id = ?
        AND enrollments.access_granted = 'Yes'
        AND trainings.active = 'Yes'
    """, (current_user.id,)).fetchall()

    return render_template("trainings.html", trainings=rows)

@app.route("/tickets")
@login_required
def tickets():
    db = get_db()
    rows = db.execute("""
        SELECT * FROM tickets
        WHERE client_id = ?
        ORDER BY created_at DESC
    """, (current_user.id,)).fetchall()

    return render_template("tickets.html", tickets=rows)


@app.route("/new-ticket", methods=["GET", "POST"])
@login_required
def new_ticket():
    if request.method == "POST":
        subject = request.form["subject"]
        category = request.form["category"]
        priority = request.form["priority"]
        description = request.form["description"]

        db = get_db()
        db.execute("""
            INSERT INTO tickets 
            (client_id, subject, category, priority, description)
            VALUES (?, ?, ?, ?, ?)
        """, (current_user.id, subject, category, priority, description))
        db.commit()

        flash("Ticket submitted successfully.")
        return redirect(url_for("tickets"))

    return render_template("new_ticket.html")


@app.route("/ticket/<int:ticket_id>")
@login_required
def ticket_detail(ticket_id):
    db = get_db()

    ticket = db.execute("""
        SELECT * FROM tickets
        WHERE id = ? AND client_id = ?
    """, (ticket_id, current_user.id)).fetchone()

    if not ticket:
        flash("Ticket not found.")
        return redirect(url_for("tickets"))

    messages = db.execute("""
        SELECT * FROM ticket_messages
        WHERE ticket_id = ?
        ORDER BY created_at ASC
    """, (ticket_id,)).fetchall()

    return render_template("ticket_detail.html", ticket=ticket, messages=messages)
    
@app.route("/admin/tickets")
@login_required
def admin_tickets():
    if not is_admin_user():
        flash("Admin access required.")
        return redirect(url_for("dashboard"))

    db = get_db()

    tickets = db.execute("""
        SELECT tickets.*, clients.name, clients.email
        FROM tickets
        LEFT JOIN clients ON tickets.client_id = clients.id
        ORDER BY tickets.created_at DESC
    """).fetchall()

    return render_template("admin_tickets.html", tickets=tickets)
    
    
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)