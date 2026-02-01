import sqlite3
from datetime import datetime, timedelta
from config import DB_PATH

DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                company     TEXT NOT NULL,
                location    TEXT,
                url         TEXT UNIQUE,
                source      TEXT,
                description TEXT,
                discovered  TEXT DEFAULT (datetime('now')),
                status      TEXT DEFAULT 'new',
                notes       TEXT,
                salary      TEXT
            );

            CREATE TABLE IF NOT EXISTS applications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          INTEGER REFERENCES jobs(id),
                company         TEXT NOT NULL,
                role            TEXT NOT NULL,
                applied_date    TEXT,
                cover_letter    TEXT,
                outreach_msg    TEXT,
                status          TEXT DEFAULT 'applied',
                follow_up_date  TEXT,
                interview_date  TEXT,
                notes           TEXT,
                response        TEXT
            );

            CREATE TABLE IF NOT EXISTS email_queue (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                company         TEXT NOT NULL,
                contact_name    TEXT,
                contact_email   TEXT,
                email_confidence INTEGER DEFAULT 0,
                subject         TEXT,
                body            TEXT,
                status          TEXT DEFAULT 'pending',
                created         TEXT DEFAULT (datetime('now')),
                sent_at         TEXT,
                error           TEXT,
                hunter_method   TEXT
            );

            CREATE TABLE IF NOT EXISTS domain_patterns (
                domain      TEXT PRIMARY KEY,
                pattern     TEXT,
                checked     TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS companies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT UNIQUE NOT NULL,
                website     TEXT,
                careers_url TEXT,
                sector      TEXT,
                size        TEXT,
                notes       TEXT,
                status      TEXT DEFAULT 'target',
                contacted   INTEGER DEFAULT 0,
                contact_name TEXT,
                contact_url TEXT
            );
        """)
        # Migrate existing DBs — add columns introduced after initial schema
        for stmt in [
            "ALTER TABLE email_queue ADD COLUMN company_id INTEGER REFERENCES companies(id)",
            "ALTER TABLE companies ADD COLUMN has_ucl_alumni INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(stmt)
            except Exception:
                pass  # column already exists


# ── Jobs ──────────────────────────────────────────────────────────────────────

def insert_job(title, company, location, url, source, description="", salary=""):
    """Insert job; silently skip if URL already exists. Returns (id, is_new)."""
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
        if existing:
            return existing["id"], False
        cur = conn.execute(
            "INSERT INTO jobs (title, company, location, url, source, description, salary) VALUES (?,?,?,?,?,?,?)",
            (title, company, location, url, source, description, salary)
        )
        return cur.lastrowid, True


def get_jobs(status=None, limit=200):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY discovered DESC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY discovered DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def update_job_status(job_id, status, notes=""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET status=?, notes=? WHERE id=?",
            (status, notes, job_id)
        )


# ── Applications ──────────────────────────────────────────────────────────────

def log_application(job_id, company, role, cover_letter="", outreach_msg="", notes=""):
    applied = datetime.now().strftime("%Y-%m-%d")
    follow_up = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO applications
               (job_id, company, role, applied_date, cover_letter, outreach_msg, follow_up_date, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job_id, company, role, applied, cover_letter, outreach_msg, follow_up, notes)
        )
        conn.execute("UPDATE jobs SET status='applied' WHERE id=?", (job_id,))
        return cur.lastrowid


def get_applications(status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM applications WHERE status=? ORDER BY applied_date DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM applications ORDER BY applied_date DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def update_application(app_id, **kwargs):
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [app_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE applications SET {fields} WHERE id=?", values)


def get_stats():
    with get_conn() as conn:
        total_apps   = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        pending      = conn.execute("SELECT COUNT(*) FROM applications WHERE status='applied'").fetchone()[0]
        interviews   = conn.execute("SELECT COUNT(*) FROM applications WHERE status='interview'").fetchone()[0]
        offers       = conn.execute("SELECT COUNT(*) FROM applications WHERE status='offer'").fetchone()[0]
        new_jobs     = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='new'").fetchone()[0]
        emails_sent  = conn.execute("SELECT COUNT(*) FROM email_queue WHERE status='sent'").fetchone()[0]
        emails_queue = conn.execute("SELECT COUNT(*) FROM email_queue WHERE status IN ('pending','approved')").fetchone()[0]
        return {
            "total_applications": total_apps,
            "pending_response": pending,
            "interviews": interviews,
            "offers": offers,
            "new_jobs_queued": new_jobs,
            "emails_sent_total": emails_sent,
            "emails_in_queue": emails_queue,
        }


# ── Email queue ───────────────────────────────────────────────────────────────

def queue_email(company, contact_name, contact_email, subject, body,
                email_confidence=0, hunter_method="", company_id=None):
    """Add email to queue. Skips silently if an active entry for (company, contact_email) exists."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM email_queue WHERE company=? AND contact_email=? AND status NOT IN ('sent','skipped','failed')",
            (company, contact_email)
        ).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute(
            """INSERT INTO email_queue
               (company, contact_name, contact_email, subject, body, email_confidence, hunter_method, company_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (company, contact_name, contact_email, subject, body, email_confidence, hunter_method, company_id)
        )
        return cur.lastrowid


def get_email_queue(status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM email_queue WHERE status=? ORDER BY created DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM email_queue ORDER BY created DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def update_queue_item(queue_id, **kwargs):
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [queue_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE email_queue SET {fields} WHERE id=?", values)


def approve_email(queue_id):
    update_queue_item(queue_id, status="approved")


def skip_email(queue_id):
    update_queue_item(queue_id, status="skipped")


# ── Domain pattern cache ──────────────────────────────────────────────────────

def cache_domain_pattern(domain: str, pattern: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO domain_patterns (domain, pattern, checked) VALUES (?,?,datetime('now'))",
            (domain, pattern)
        )


def get_cached_pattern(domain: str) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT pattern FROM domain_patterns WHERE domain=?", (domain,)).fetchone()
        return row["pattern"] if row else ""


# ── Companies ─────────────────────────────────────────────────────────────────

def upsert_company(name, website="", careers_url="", sector="", size="", notes="", status="target"):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM companies WHERE name=?", (name,)).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO companies (name, website, careers_url, sector, size, notes, status) VALUES (?,?,?,?,?,?,?)",
            (name, website, careers_url, sector, size, notes, status)
        )
        return cur.lastrowid


def get_companies(status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM companies WHERE status=? ORDER BY name", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM companies ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_overdue_followups():
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM applications WHERE status='applied' AND follow_up_date <= ? ORDER BY follow_up_date",
            (today,)
        ).fetchall()
        return [dict(r) for r in rows]


def count_followups_for_company(company: str) -> int:
    """Return how many follow-up emails have been queued or sent for this company."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM email_queue WHERE company=? AND hunter_method='followup'",
            (company,)
        ).fetchone()
        return row[0] if row else 0


def get_sent_email_for_company(company: str) -> dict | None:
    """Return the most recent sent email for a company, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM email_queue WHERE company=? AND status='sent' ORDER BY sent_at DESC LIMIT 1",
            (company,)
        ).fetchone()
        return dict(row) if row else None


def update_company(company_id, **kwargs):
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [company_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE companies SET {fields} WHERE id=?", values)


init_db()
