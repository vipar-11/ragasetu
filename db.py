"""SQLite database initialization, authentication helpers, and data access for ragasetu."""

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone

SONG_CATEGORIES = [
    "Bhajan",
    "Kriti",
    "Carnatic - Basic",
    "Carnatic - Geetham",
    "Carnatic - Varnam",
    "Carnatic - Keerthanai",
    "Thirupugazh",
    "Thevaram",
]

STUDENT_LEVELS = [
    "Beginner",
    "Intermediate",
    "Advanced",
]

COMPONENT_TYPES = [
    "lyrics",
    "full_audio",
    "thalam_video",
    "multipart_audio",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_password(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, expected = stored_hash.split("$", 1)
    except ValueError:
        return False
    actual = hash_password(password, salt).split("$", 1)[1]
    return hmac.compare_digest(actual, expected)


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = get_connection(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('teacher', 'student')),
                level TEXT NOT NULL DEFAULT 'Beginner',
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                ragam TEXT DEFAULT '',
                thalam TEXT DEFAULT '',
                composer TEXT DEFAULT '',
                target_level TEXT NOT NULL DEFAULT 'All Levels',
                lyrics_text TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                uploaded_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS song_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
                component_type TEXT NOT NULL CHECK(
                    component_type IN ('lyrics', 'full_audio', 'thalam_video', 'multipart_audio')
                ),
                part_label TEXT DEFAULT '',
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS class_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                target_level TEXT NOT NULL DEFAULT 'All Levels',
                attachment_original_name TEXT DEFAULT '',
                attachment_stored_name TEXT DEFAULT '',
                attachment_mime_type TEXT DEFAULT '',
                posted_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS class_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                day_or_date TEXT NOT NULL,
                time_slot TEXT NOT NULL,
                target_level TEXT NOT NULL DEFAULT 'All Levels',
                location_or_link TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
        _seed_defaults(conn)
    finally:
        conn.close()


def _seed_defaults(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()["cnt"]
    if existing > 0:
        return

    now = utc_now_iso()
    users = [
        ("guru", "Vidushi Meenakshi (Teacher)", "teacher", "Teacher", hash_password("guru123")),
        ("ananya", "Ananya Rao", "student", "Beginner", hash_password("student123")),
        ("karthik", "Karthik Iyer", "student", "Intermediate", hash_password("student123")),
        ("divya", "Divya Krishnan", "student", "Advanced", hash_password("student123")),
    ]
    conn.executemany(
        "INSERT INTO users (username, full_name, role, level, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [(u, n, r, l, h, now) for (u, n, r, l, h) in users],
    )
    teacher_id = conn.execute("SELECT id FROM users WHERE username = 'guru'").fetchone()["id"]

    schedules = [
        (
            "Sarali & Janta Varisai Practice",
            "Every Tuesday",
            "6:00 PM - 7:00 PM",
            "Beginner",
            "Online / Studio Room A",
            "Focus on 3 speeds (Trikaalam) with Adi Thalam.",
            teacher_id,
            now,
        ),
        (
            "Geetham & Varnam Batch",
            "Every Thursday",
            "6:30 PM - 7:45 PM",
            "Intermediate",
            "Online / Studio Room A",
            "Revision of Lambodara Lakumikara and Mohanam Varnam.",
            teacher_id,
            now,
        ),
        (
            "Kriti & Manodharma Session",
            "Every Saturday",
            "9:00 AM - 10:30 AM",
            "Advanced",
            "Main Hall",
            "Neraval and Kalpana Swaram practice.",
            teacher_id,
            now,
        ),
        (
            "Group Bhajan & Thirupugazh",
            "Every Sunday",
            "10:00 AM - 11:00 AM",
            "All Levels",
            "Main Hall",
            "Combined ensemble practice for upcoming Navaratri program.",
            teacher_id,
            now,
        ),
    ]
    conn.executemany(
        """INSERT INTO class_schedule
           (title, day_or_date, time_slot, target_level, location_or_link, notes, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        schedules,
    )

    conn.execute(
        """INSERT INTO class_updates
           (title, message, target_level, posted_by, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            "Welcome to ragasetu!",
            "All lesson lyrics, full audio recordings, thalam videos, and multi-part practice tracks will be posted here. Please practice with sruti box at 4.5 katta / F#.",
            "All Levels",
            teacher_id,
            now,
        ),
    )

    conn.execute(
        """INSERT INTO songs
           (title, category, ragam, thalam, composer, target_level, lyrics_text, notes, uploaded_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "Lambodara Lakumikara",
            "Carnatic - Geetham",
            "Malahari",
            "Rupakam",
            "Purandara Dasa",
            "Beginner",
            "Pallavi:\nSree Gananatha Sindhoora Varna\nKaruna Sagara Kari Vadana\n\nCharanam:\nLambodara Lakumikara\nAmba Suta Amara Vinuta",
            "First geetham taught after alankarams. Keep steady Rupaka thalam.",
            teacher_id,
            now,
        ),
    )
    conn.commit()

