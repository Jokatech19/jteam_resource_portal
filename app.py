import sqlite3
import os
import smtplib
import psycopg2
import requests
import psycopg2.extras
import mimetypes
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for, flash, g
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
#DB_PATH = r"C:\Users\Jokatech\Desktop\dist\JayDB\jokatech_business.db"
DB_PATH = os.path.join(BASE_DIR, "jokatech_business.db")
app = Flask(__name__)
app.secret_key = "change-this-secret-key"
EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "false").lower() == "true"
print("EMAIL_ENABLED raw value:", repr(os.environ.get("EMAIL_ENABLED")))
print("EMAIL_ENABLED parsed value:", EMAIL_ENABLED)
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

def send_email(to_email, subject, body, attachment_path=None, attachment_name=None):
    if not EMAIL_ENABLED:
        print("Email disabled. Skipping send.")
        return False

    try:
        smtp_server = os.environ.get("SMTP_SERVER")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_username = os.environ.get("SMTP_USERNAME")
        smtp_password = os.environ.get("SMTP_PASSWORD")
        from_email = os.environ.get("FROM_EMAIL", smtp_username)

        if not all([
            smtp_server,
            smtp_username,
            smtp_password,
            from_email,
            to_email
        ]):
            print("Email not sent: SMTP configuration is incomplete.")
            return False

        msg = EmailMessage()
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        if attachment_path and os.path.exists(attachment_path):
            mime_type, _ = mimetypes.guess_type(attachment_path)

            if mime_type:
                maintype, subtype = mime_type.split("/", 1)
            else:
                maintype, subtype = "application", "octet-stream"

            with open(attachment_path, "rb") as f:
                msg.add_attachment(
                    f.read(),
                    maintype=maintype,
                    subtype=subtype,
                    filename=attachment_name or os.path.basename(attachment_path)
                )
        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)

        print(f"Email sent successfully to {to_email}")
        return True

    except Exception as error:
        print(f"Email failed: {type(error).__name__}: {error}")
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

    db.execute("""
    CREATE TABLE IF NOT EXISTS AI_Image2Vid (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        ticket_id INTEGER,
        RefImg TEXT,
        AnimPrompt TEXT,
        Dur INTEGER,
        Status TEXT DEFAULT 'Pending Approval',
        CPromptID TEXT,
        OutName TEXT,
        AdminApp TEXT DEFAULT 'No'
    )
    """)
    
    try:
        db.execute("ALTER TABLE AI_Image2Vid ADD COLUMN client_id INTEGER")
    except sqlite3.OperationalError:
        pass

    try:
        db.execute("ALTER TABLE AI_Image2Vid ADD COLUMN ticket_id INTEGER")
    except sqlite3.OperationalError:
        pass

    db.commit()
def notify_portal_activity(
    event,
    name="",
    email="",
    product="",
    status="",
    notify_client=False,
    password_hash=""
):
    webhook = os.environ.get("GOOGLE_ACTIVITY_WEBHOOK")

    if not webhook:
        print("Google activity webhook is not configured.")
        return False

    try:
        response = requests.post(
            webhook,
            json={
                "event": event,
                "name": name,
                "email": email,
                "product": product,
                "status": status,
                "notify_client": notify_client,
                "password_hash": password_hash
            },
            timeout=10
        )

        print(
            "Portal notification:",
            response.status_code,
            response.text
        )

        return response.ok

    except Exception as error:
        print("Notification failed:", error)
        return False
  
def notify_ticket_activity(
    event,
    ticket_id="",
    client_id="",
    name="",
    email="",
    subject="",
    category="",
    priority="",
    message="",
    status="",
    sender_type=""
):
    webhook = os.environ.get("GOOGLE_ACTIVITY_WEBHOOK")

    if not webhook:
        print("Google activity webhook is not configured.")
        return False

    try:
        response = requests.post(
            webhook,
            json={
                "event": event,
                "ticket_id": ticket_id,
                "client_id": client_id,
                "name": name,
                "email": email,
                "subject": subject,
                "category": category,
                "priority": priority,
                "message": message,
                "status": status,
                "sender_type": sender_type
            },
            timeout=10
        )

        print(
            "Ticket backup:",
            response.status_code,
            response.text
        )

        return response.ok

    except Exception as error:
        print("Ticket backup failed:", error)
        return False  
@app.before_request
def before_request():
    setup_tables()


@app.route("/")
def home():
    return redirect(url_for("login"))


#@app.route("/register", methods=["GET", "POST"])
#def register():
 #   if request.method == "POST":
  #      name = request.form["name"]
   #     email = request.form["email"]
    #    password = request.form["password"]
#
 #       db = get_db()
  #     try:
   #         db.execute(
    #            "INSERT INTO clients (name, email, password_hash) VALUES (?, ?, ?)",
     #           (name, email, generate_password_hash(password))
      #      )
       #     db.commit()
        #    flash("Account created. You can log in now.")
         #   return redirect(url_for("login"))
        #except sqlite3.IntegrityError:
         #   flash("That email already exists.")
#
 #   return render_template("login.html", register=True)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        db = get_db()

        try:
            password_hash = generate_password_hash(password)
            db.execute(
                "INSERT INTO clients (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, password_hash)
            )
            db.commit()
            notify_portal_activity(
                event="New Client Registration",
                name=name,
                email=email,
                status="Registered",
                notify_client=True,
                password_hash=password_hash
)
            admin_email = os.environ.get("ADMIN_EMAIL")

            if admin_email:
                send_email(
                    admin_email,
                    "New J-Team Resource Client Registration",
                    (
                        "A new client created a portal account.\n\n"
                        f"Name: {name}\n"
                        f"Email: {email}\n\n"
                        "Log in to the admin portal to review the member."
                    )
                )

            # Optional welcome email to the new client
            send_email(
                email,
                "Welcome to J-Team Resource",
                (
                    f"Hello {name},\n\n"
                    "Your J-Team Resource portal account has been created.\n\n"
                    "You can now sign in to view training, software, "
                    "support tickets, and resources available to your account."
                )
            )

            flash("Account created. You can log in now.")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("That email address is already registered.")

    return render_template("login.html", register=True)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        db = get_db()

        user = db.execute(
            "SELECT * FROM clients WHERE email = ?",
            (email,)
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            login_user(User(user))

            if user["is_admin"] == "Yes":
                return redirect(url_for("admin_dashboard"))

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
        cursor = db.execute("""
            INSERT INTO tickets 
            (client_id, subject, category, priority, description)
            VALUES (?, ?, ?, ?, ?)
        """, (current_user.id, subject, category, priority, description))
        ticket_id = cursor.lastrowid
        db.commit()
    
        notify_ticket_activity(
            event="New Ticket",
            ticket_id=ticket_id,
            client_id=current_user.id,
            name=current_user.name,
            email=current_user.email,
            subject=subject,
            category=category,
            priority=priority,
            message=description,
            status="Open",
            sender_type="client"
)
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

@app.route("/ai-video-request", methods=["GET", "POST"])
@login_required
def ai_video_request():
    if request.method == "POST":
        anim_prompt = request.form["anim_prompt"].strip()
        duration = int(request.form.get("duration", 4))
    
        ref_image = request.files.get("ref_image")

        if not ref_image or ref_image.filename == "":
            flash("Please upload a reference image.")
            return redirect(url_for("ai_video_request"))

        filename = secure_filename(ref_image.filename)

        upload_folder = os.path.join(BASE_DIR, "static", "uploads", "ai_video")
        os.makedirs(upload_folder, exist_ok=True)

        saved_path = os.path.join(upload_folder, filename)
        ref_image.save(saved_path)
        db = get_db()

        cursor = db.execute("""
            INSERT INTO tickets
            (client_id, subject, category, priority, status, description)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            current_user.id,
            "AI Image-to-Video Request",
            "AI Video Generation",
            "Normal",
            "Open",
            anim_prompt
        ))

        ticket_id = cursor.lastrowid

        db.execute("""
            INSERT INTO AI_Image2Vid
            (client_id, ticket_id, RefImg, AnimPrompt, Dur, Status, AdminApp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            current_user.id,
            ticket_id,
            filename,
            anim_prompt,
            duration,
            "Pending Approval",
            "No"
        ))

        db.commit()
        notify_ticket_activity(
            event="New Ticket",
            ticket_id=ticket_id,
            client_id=current_user.id,
            name=current_user.name,
            email=current_user.email,
            subject="AI Image-to-Video Request",
            category="AI Video Generation",
            priority="Normal",
            message=(
                f"AI VIDEO REQUEST\n"
                f"Reference Image: {filename}\n"
                f"Duration: {duration} seconds\n"
                f"Status: Pending Approval\n\n"
                f"Animation Prompt:\n{anim_prompt}"
            ),
            status="Pending Approval",
            sender_type="client"
)
        admin_email = os.environ.get("ADMIN_EMAIL")

        if admin_email:
            send_email(
                admin_email,
                "New AI Image-to-Video Request",
                (
                    f"A new AI video request was submitted by {current_user.name}.\n\n"
                    f"Client Email: {current_user.email}\n"
                    f"Ticket ID: {ticket_id}\n"
                    f"Requested Duration: {duration} seconds\n"
                    f"Reference Image: {filename}\n\n"
                    f"Animation Prompt:\n{anim_prompt}\n\n"
                    "Log in to the admin portal to review and approve the request."
                ),
                attachment_path=saved_path,
                attachment_name=filename
        )
        flash("AI video request submitted for approval.")
        return redirect(url_for("tickets"))

    return render_template("ai_video_request.html")

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
    
    ai_request = db.execute("""
    SELECT *
    FROM AI_Image2Vid
    WHERE ticket_id = ?
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

    return render_template("admin_ticket_detail.html", ticket=ticket, messages=messages, ai_request=ai_request)
  

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
    
@app.route("/software-catalog")
@login_required
def software_catalog():
    db = get_db()
    tools = db.execute("""
        SELECT *
        FROM software_tools
        WHERE active = 'Yes'
        ORDER BY title
    """).fetchall()

    return render_template("software_catalog.html", tools=tools)


@app.route("/my-software")
@login_required
def my_software():
    db = get_db()
    tools = db.execute("""
        SELECT software_tools.*
        FROM software_tools
        JOIN software_access ON software_tools.id = software_access.software_id
        WHERE software_access.client_id = ?
        AND software_access.access_granted = 'Yes'
        AND software_tools.active = 'Yes'
        ORDER BY software_tools.title
    """, (current_user.id,)).fetchall()

    return render_template("my_software.html", tools=tools)
    
@app.route("/admin/members")
@login_required
def admin_members():
    if not is_admin_user():
        flash("Admin access required.")
        return redirect(url_for("dashboard"))

    db = get_db()
    members = db.execute("""
        SELECT id, name, email, payment_status, is_admin
        FROM clients
        ORDER BY id DESC
    """).fetchall()

    return render_template("admin_members.html", members=members)
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)