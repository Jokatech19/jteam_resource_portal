import sqlite3
import os
import smtplib
import psycopg2
import psycopg2.extras
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for, flash, g
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
#DB_PATH = r"C:\Users\Jokatech\Desktop\dist\JayDB\jokatech_business.db"
DB_PATH = os.path.join(BASE_DIR, "jokatech_business.db")
app = Flask(__name__)
app.secret_key = "change-this-secret-key"
EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "false").lower() == "true"
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class DatabaseWrapper:
    def __init__(self, conn, is_postgres=False):
        self.conn = conn
        self.is_postgres = is_postgres

    def execute(self, query, params=()):
        if self.is_postgres:
            query = query.replace("?", "%s")
            query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            cur = self.conn.cursor()
            cur.execute(query, params)
            return cur
        else:
            return self.conn.execute(query, params)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def get_db():
    if "db" not in g:
        database_url = os.environ.get("DATABASE_URL")

        if database_url:
            conn = psycopg2.connect(
                database_url,
                cursor_factory=psycopg2.extras.RealDictCursor
            )
            g.db = DatabaseWrapper(conn, is_postgres=True)
        else:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            g.db = DatabaseWrapper(conn, is_postgres=False)

    return g.db

def send_email(to_email, subject, body):
    if not EMAIL_ENABLED:
        print("Email disabled. Skipping send.")
        return False

    try:
        smtp_server = os.environ.get("SMTP_SERVER")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_username = os.environ.get("SMTP_USERNAME")
        smtp_password = os.environ.get("SMTP_PASSWORD")
        from_email = os.environ.get("FROM_EMAIL", smtp_username)

        if not smtp_server or not smtp_username or not smtp_password:
            print("Email not sent: SMTP settings missing.")
            return False

        msg = EmailMessage()
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)

        print(f"Email sent to {to_email}")
        return True

    except Exception as e:
        print(f"Email failed: {e}")
        return False

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
        #self.is_admin = row["is_admin"] if "is_admin" in row.keys() else "No"
        #self.is_admin = row.get("is_admin", "No")

        try:
            self.is_admin = row["is_admin"]
        except (KeyError, IndexError):
            self.is_admin = "No"
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
    try:
        db.execute("ALTER TABLE trainings ADD COLUMN paypal_url TEXT")
    except sqlite3.OperationalError:
        pass
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
    try:
        db.execute("ALTER TABLE tickets ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
    except sqlite3.OperationalError:
        pass

    try:
        db.execute("ALTER TABLE tickets ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    db.execute("""
    CREATE TABLE IF NOT EXISTS ticket_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER,
        sender_type TEXT,
        message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    try:
        db.execute("ALTER TABLE ticket_messages ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE ticket_messages ADD COLUMN sender_type TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE ticket_messages ADD COLUMN message TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        db.execute("ALTER TABLE ticket_messages ADD COLUMN sender_type TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        db.execute("ALTER TABLE ticket_messages ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
    except sqlite3.OperationalError:
        pass

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

@app.route("/training-catalog")
@login_required
def training_catalog():
    db = get_db()

    trainings = db.execute("""
        SELECT *
        FROM trainings
        WHERE active = 'Yes'
        ORDER BY title
    """).fetchall()

    return render_template("training_catalog.html", trainings=trainings)
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

        admin_email = os.environ.get("ADMIN_EMAIL")

        if admin_email:
            send_email(
                admin_email,
                "New J-Team Resource Ticket Submitted",
                f"A new ticket was submitted by {current_user.name}.\n\n"
                f"Subject: {subject}\n"
                f"Category: {category}\n"
                f"Priority: {priority}\n\n"
                f"Description:\n{description}"
            )

        flash("Ticket submitted successfully.")
        return redirect(url_for("tickets"))

    return render_template("new_ticket.html")


@app.route("/ticket/<int:ticket_id>", methods=["GET", "POST"])
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

    if request.method == "POST":
        message = request.form.get("message", "").strip()

        if message:
            db.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_type, message)
                VALUES (?, ?, ?)
            """, (ticket_id, "Client", message))

            db.execute("""
                UPDATE tickets
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (ticket_id,))

            db.commit()

            admin_email = os.environ.get("ADMIN_EMAIL")
            if admin_email:
                send_email(
                    admin_email,
                    f"Client Reply on Ticket #{ticket_id}",
                    f"{current_user.name} replied to ticket #{ticket_id}.\n\nMessage:\n{message}"
                )

            flash("Reply sent.")

        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

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
#ADDED
@app.route("/admin/ticket/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def admin_ticket_detail(ticket_id):
    if not is_admin_user():
        flash("Admin access required.")
        return redirect(url_for("dashboard"))

    db = get_db()

    ticket = db.execute("""
        SELECT tickets.*, clients.name, clients.email
        FROM tickets
        LEFT JOIN clients ON tickets.client_id = clients.id
        WHERE tickets.id = ?
    """, (ticket_id,)).fetchone()

    if not ticket:
        flash("Ticket not found.")
        return redirect(url_for("admin_tickets"))

    if request.method == "POST":
        message = request.form.get("message", "").strip()
        status = request.form.get("status", ticket["status"])

        db.execute("""
            UPDATE tickets
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, ticket_id))

        if message:
            db.execute("""
                INSERT INTO ticket_messages (ticket_id, sender_type, message)
                VALUES (?, ?, ?)
            """, (ticket_id, "Admin", message))

            if ticket["email"]:
                send_email(
                    ticket["email"],
                    f"Response to Your J-Team Resource Ticket #{ticket_id}",
                    f"Your ticket has a new response.\n\n"
                    f"Subject: {ticket['subject']}\n\n"
                    f"Response:\n{message}\n\n"
                    f"Please log into the portal to continue the conversation."
                )

        db.commit()
        flash("Ticket updated.")
        return redirect(url_for("admin_ticket_detail", ticket_id=ticket_id))

    messages = db.execute("""
        SELECT * FROM ticket_messages
        WHERE ticket_id = ?
        ORDER BY created_at ASC
    """, (ticket_id,)).fetchall()

    return render_template("admin_ticket_detail.html", ticket=ticket, messages=messages)
  

@app.route("/admin")
@login_required
def admin_dashboard():
    if not is_admin_user():
        flash("Admin access required.")
        return redirect(url_for("dashboard"))

    return render_template("admin_dashboard.html")


@app.route("/admin/clients")
@login_required
def admin_clients():
    if not is_admin_user():
        flash("Admin access required.")
        return redirect(url_for("dashboard"))

    db = get_db()
    clients = db.execute("SELECT * FROM clients ORDER BY name").fetchall()

    return render_template("admin_clients.html", clients=clients)


@app.route("/admin/grant-access/<int:client_id>", methods=["GET", "POST"])
@login_required
def admin_grant_access(client_id):
    if not is_admin_user():
        flash("Admin access required.")
        return redirect(url_for("dashboard"))

    db = get_db()

    client = db.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    trainings = db.execute("SELECT * FROM trainings WHERE active = 'Yes' ORDER BY title").fetchall()

    if request.method == "POST":
        training_id = request.form["training_id"]

        db.execute("""
            INSERT INTO enrollments (client_id, training_id, access_granted, purchase_date)
            VALUES (?, ?, 'Yes', CURRENT_TIMESTAMP)
        """, (client_id, training_id))

        db.commit()
        flash("Training access granted.")
        return redirect(url_for("admin_clients"))
#ADDED
        send_email(
            client["email"],
            "Your J-Team Resource Training Access Is Ready",
            "Your training access has been approved. Please log into the portal and open My Trainings."
            )
    return render_template("admin_grant_access.html", client=client, trainings=trainings)  
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)