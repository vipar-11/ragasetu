"""FastAPI application for ragasetu."""

import mimetypes
import os
import re
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import (
    COMPONENT_TYPES,
    SONG_CATEGORIES,
    STUDENT_LEVELS,
    get_connection,
    hash_password,
    init_db,
    utc_now_iso,
    verify_password,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("video/quicktime", ".mov")


def safe_filename(name: str) -> str:
    base = os.path.basename(name or "file")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return cleaned or "file"


def guess_mime(filename: str, fallback: str = "application/octet-stream") -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or fallback


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    full_name: str
    role: str = "student"
    level: str = "Beginner"
    password: str


class CreateScheduleRequest(BaseModel):
    title: str
    day_or_date: str
    time_slot: str
    target_level: str = "All Levels"
    location_or_link: str = ""
    notes: str = ""


def create_app(data_dir: str | None = None) -> FastAPI:
    resolved_data_dir = os.path.abspath(data_dir or os.path.join(BASE_DIR, "data"))
    db_path = os.path.join(resolved_data_dir, "ragasetu.db")
    upload_dir = os.path.join(resolved_data_dir, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    init_db(db_path)

    app = FastAPI(
        title="ragasetu API",
        description="Classical music learning portal for teachers and students.",
        version="2.0.0",
    )

    # ---- Auth Dependencies ----

    def get_current_user(request: Request) -> dict | None:
        token = request.cookies.get("ragasetu_session")
        if not token:
            return None
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                """SELECT u.id, u.username, u.full_name, u.role, u.level
                   FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE s.token = ?""",
                (token,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def require_auth(user: dict | None = Depends(get_current_user)) -> dict:
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        return user

    def require_teacher(user: dict = Depends(require_auth)) -> dict:
        if user["role"] != "teacher":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher access required")
        return user

    # ---- File Storage Helpers ----

    async def save_upload(upload: UploadFile) -> tuple[str, str, int]:
        orig = safe_filename(upload.filename or "file")
        stored = f"{secrets.token_hex(12)}_{orig}"
        dest = os.path.join(upload_dir, stored)
        data = await upload.read()
        with open(dest, "wb") as f:
            f.write(data)
        mime = upload.content_type or "application/octet-stream"
        if mime == "application/octet-stream":
            mime = guess_mime(orig)
        return stored, mime, len(data)

    def remove_stored_file(stored_filename: str) -> None:
        if not stored_filename:
            return
        path = os.path.join(upload_dir, os.path.basename(stored_filename))
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def build_file_response(
        stored_filename: str, original_filename: str, mime_type: str, download: bool
    ) -> FileResponse:
        path = os.path.join(upload_dir, os.path.basename(stored_filename))
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="File not found on disk")
        disposition = "attachment" if download else "inline"
        return FileResponse(
            path=path,
            media_type=mime_type or "application/octet-stream",
            filename=safe_filename(original_filename),
            content_disposition_type=disposition,
        )

    def attach_song_files(conn, songs: list[dict]) -> list[dict]:
        if not songs:
            return songs
        ids = [s["id"] for s in songs]
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""SELECT id, song_id, component_type, part_label, original_filename, mime_type, size_bytes, created_at
                FROM song_files WHERE song_id IN ({placeholders}) ORDER BY id ASC""",
            ids,
        ).fetchall()
        by_song: dict[int, list[dict]] = {sid: [] for sid in ids}
        for r in rows:
            by_song[r["song_id"]].append(dict(r))
        for s in songs:
            s["files"] = by_song.get(s["id"], [])
        return songs

    async def save_song_components(
        conn,
        song_id: int,
        lyrics_file: UploadFile | None,
        full_audio: UploadFile | None,
        thalam_video: UploadFile | None,
        multipart_audio: list[UploadFile],
        multipart_label: list[str],
    ) -> None:
        now = utc_now_iso()
        singles = [
            ("lyrics", lyrics_file),
            ("full_audio", full_audio),
            ("thalam_video", thalam_video),
        ]
        for comp_type, upload in singles:
            if upload and upload.filename:
                stored, mime, size_bytes = await save_upload(upload)
                conn.execute(
                    """INSERT INTO song_files
                       (song_id, component_type, part_label, original_filename, stored_filename, mime_type, size_bytes, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (song_id, comp_type, "", upload.filename, stored, mime, size_bytes, now),
                )

        mp_idx = 0
        for upload in multipart_audio:
            if not upload or not upload.filename:
                continue
            label = (
                multipart_label[mp_idx].strip()
                if mp_idx < len(multipart_label) and multipart_label[mp_idx].strip()
                else f"Part {mp_idx + 1}"
            )
            mp_idx += 1
            stored, mime, size_bytes = await save_upload(upload)
            conn.execute(
                """INSERT INTO song_files
                   (song_id, component_type, part_label, original_filename, stored_filename, mime_type, size_bytes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (song_id, "multipart_audio", label, upload.filename, stored, mime, size_bytes, now),
            )

    # ---- Auth Routes ----

    @app.post("/api/login")
    def login(payload: LoginRequest, response: Response):
        username = payload.username.strip().lower()
        if not username or not payload.password:
            raise HTTPException(status_code=400, detail="Username and password are required")

        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT id, username, full_name, role, level, password_hash FROM users WHERE LOWER(username) = ?",
                (username,),
            ).fetchone()
            if not row or not verify_password(payload.password, row["password_hash"]):
                raise HTTPException(status_code=401, detail="Invalid username or password")

            token = secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                (token, row["id"], utc_now_iso()),
            )
            conn.commit()
            user = {
                "id": row["id"],
                "username": row["username"],
                "full_name": row["full_name"],
                "role": row["role"],
                "level": row["level"],
            }
            response.set_cookie(
                key="ragasetu_session",
                value=token,
                httponly=True,
                path="/",
                samesite="lax",
            )
            return {"user": user}
        finally:
            conn.close()

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get("ragasetu_session")
        if token:
            conn = get_connection(db_path)
            try:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                conn.commit()
            finally:
                conn.close()
        response.delete_cookie("ragasetu_session", path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(user: dict | None = Depends(get_current_user)):
        return {
            "user": user,
            "meta": {
                "categories": SONG_CATEGORIES,
                "levels": STUDENT_LEVELS,
                "component_types": COMPONENT_TYPES,
            },
        }

    # ---- User Routes (Teacher Only) ----

    @app.get("/api/users")
    def list_users(_teacher: dict = Depends(require_teacher)):
        conn = get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT id, username, full_name, role, level, created_at FROM users ORDER BY role DESC, full_name ASC"
            ).fetchall()
            return {"users": [dict(r) for r in rows]}
        finally:
            conn.close()

    @app.post("/api/users", status_code=201)
    def create_user(payload: CreateUserRequest, _teacher: dict = Depends(require_teacher)):
        username = payload.username.strip().lower()
        full_name = payload.full_name.strip()
        role = payload.role.strip().lower()
        level = payload.level.strip()

        if not username or not full_name or not payload.password:
            raise HTTPException(status_code=400, detail="Username, full name, and password are required")
        if role not in ("teacher", "student"):
            raise HTTPException(status_code=400, detail="Role must be teacher or student")
        if role == "student" and level not in STUDENT_LEVELS:
            raise HTTPException(status_code=400, detail=f"Level must be one of: {', '.join(STUDENT_LEVELS)}")
        if role == "teacher":
            level = "Teacher"

        conn = get_connection(db_path)
        try:
            existing = conn.execute("SELECT id FROM users WHERE LOWER(username) = ?", (username,)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="Username already exists")
            cur = conn.execute(
                "INSERT INTO users (username, full_name, role, level, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (username, full_name, role, level, hash_password(payload.password), utc_now_iso()),
            )
            conn.commit()
            user_row = conn.execute(
                "SELECT id, username, full_name, role, level, created_at FROM users WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            return {"user": dict(user_row)}
        finally:
            conn.close()

    @app.delete("/api/users/{user_id}")
    def delete_user(user_id: int, teacher: dict = Depends(require_teacher)):
        if teacher["id"] == user_id:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")
        conn = get_connection(db_path)
        try:
            cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="User not found")
            return {"ok": True}
        finally:
            conn.close()

    # ---- Song Routes ----

    @app.get("/api/songs")
    def list_songs(
        category: str = "",
        level: str = "",
        q: str = "",
        _user: dict = Depends(require_auth),
    ):
        sql = """SELECT s.*, u.full_name AS teacher_name
                 FROM songs s
                 JOIN users u ON u.id = s.uploaded_by
                 WHERE 1=1"""
        params: list = []
        if category.strip() and category.strip() != "All":
            sql += " AND s.category = ?"
            params.append(category.strip())
        if level.strip() and level.strip() != "All":
            sql += " AND (s.target_level = ? OR s.target_level = 'All Levels')"
            params.append(level.strip())
        if q.strip():
            sql += " AND (LOWER(s.title) LIKE ? OR LOWER(s.ragam) LIKE ? OR LOWER(s.thalam) LIKE ? OR LOWER(s.composer) LIKE ?)"
            like = f"%{q.strip().lower()}%"
            params.extend([like, like, like, like])
        sql += " ORDER BY s.created_at DESC, s.id DESC"

        conn = get_connection(db_path)
        try:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
            attach_song_files(conn, rows)
            return {"songs": rows}
        finally:
            conn.close()

    @app.get("/api/songs/{song_id}")
    def get_song(song_id: int, _user: dict = Depends(require_auth)):
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                """SELECT s.*, u.full_name AS teacher_name
                   FROM songs s
                   JOIN users u ON u.id = s.uploaded_by
                   WHERE s.id = ?""",
                (song_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Song not found")
            song = attach_song_files(conn, [dict(row)])[0]
            return {"song": song}
        finally:
            conn.close()

    @app.post("/api/songs", status_code=201)
    async def create_song(
        title: Annotated[str, Form()] = "",
        category: Annotated[str, Form()] = "",
        ragam: Annotated[str, Form()] = "",
        thalam: Annotated[str, Form()] = "",
        composer: Annotated[str, Form()] = "",
        target_level: Annotated[str, Form()] = "All Levels",
        lyrics_text: Annotated[str, Form()] = "",
        notes: Annotated[str, Form()] = "",
        multipart_label: Annotated[list[str], Form()] = [],
        lyrics_file: Annotated[UploadFile | None, File()] = None,
        full_audio: Annotated[UploadFile | None, File()] = None,
        thalam_video: Annotated[UploadFile | None, File()] = None,
        multipart_audio: Annotated[list[UploadFile], File()] = [],
        teacher: dict = Depends(require_teacher),
    ):
        clean_title = title.strip()
        clean_cat = category.strip()
        if not clean_title:
            raise HTTPException(status_code=400, detail="Song title is required")
        if clean_cat not in SONG_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Category must be one of: {', '.join(SONG_CATEGORIES)}")

        conn = get_connection(db_path)
        try:
            cur = conn.execute(
                """INSERT INTO songs
                   (title, category, ragam, thalam, composer, target_level, lyrics_text, notes, uploaded_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    clean_title,
                    clean_cat,
                    ragam.strip(),
                    thalam.strip(),
                    composer.strip(),
                    target_level.strip() or "All Levels",
                    lyrics_text.strip(),
                    notes.strip(),
                    teacher["id"],
                    utc_now_iso(),
                ),
            )
            song_id = cur.lastrowid
            await save_song_components(
                conn,
                song_id,
                lyrics_file=lyrics_file,
                full_audio=full_audio,
                thalam_video=thalam_video,
                multipart_audio=multipart_audio,
                multipart_label=multipart_label,
            )
            conn.commit()
            row = conn.execute(
                """SELECT s.*, u.full_name AS teacher_name
                   FROM songs s JOIN users u ON u.id = s.uploaded_by WHERE s.id = ?""",
                (song_id,),
            ).fetchone()
            song = attach_song_files(conn, [dict(row)])[0]
            return {"song": song}
        finally:
            conn.close()

    @app.delete("/api/songs/{song_id}")
    def delete_song(song_id: int, _teacher: dict = Depends(require_teacher)):
        conn = get_connection(db_path)
        try:
            file_rows = conn.execute("SELECT stored_filename FROM song_files WHERE song_id = ?", (song_id,)).fetchall()
            cur = conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Song not found")
            for fr in file_rows:
                remove_stored_file(fr["stored_filename"])
            return {"ok": True}
        finally:
            conn.close()

    @app.get("/api/files/{file_id}")
    def get_file(
        file_id: int,
        download: int = Query(0),
        _user: dict = Depends(require_auth),
    ):
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT original_filename, stored_filename, mime_type FROM song_files WHERE id = ?",
                (file_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="File not found")
        return build_file_response(
            row["stored_filename"], row["original_filename"], row["mime_type"], bool(download)
        )

    @app.delete("/api/files/{file_id}")
    def delete_file(file_id: int, _teacher: dict = Depends(require_teacher)):
        conn = get_connection(db_path)
        try:
            row = conn.execute("SELECT stored_filename FROM song_files WHERE id = ?", (file_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="File not found")
            conn.execute("DELETE FROM song_files WHERE id = ?", (file_id,))
            conn.commit()
            remove_stored_file(row["stored_filename"])
            return {"ok": True}
        finally:
            conn.close()

    # ---- Class Updates Routes ----

    @app.get("/api/updates")
    def list_updates(_user: dict = Depends(require_auth)):
        conn = get_connection(db_path)
        try:
            rows = conn.execute(
                """SELECT u_upd.id, u_upd.title, u_upd.message, u_upd.target_level,
                          u_upd.attachment_original_name, u_upd.attachment_mime_type,
                          u_upd.created_at, usr.full_name AS author_name
                   FROM class_updates u_upd
                   JOIN users usr ON usr.id = u_upd.posted_by
                   ORDER BY u_upd.created_at DESC, u_upd.id DESC"""
            ).fetchall()
            return {"updates": [dict(r) for r in rows]}
        finally:
            conn.close()

    @app.post("/api/updates", status_code=201)
    async def create_update(
        title: Annotated[str, Form()] = "",
        message: Annotated[str, Form()] = "",
        target_level: Annotated[str, Form()] = "All Levels",
        attachment: Annotated[UploadFile | None, File()] = None,
        teacher: dict = Depends(require_teacher),
    ):
        clean_title = title.strip()
        clean_msg = message.strip()
        if not clean_title or not clean_msg:
            raise HTTPException(status_code=400, detail="Title and message are required")

        orig_name, stored_name, mime = "", "", ""
        if attachment and attachment.filename:
            stored_name, mime, _ = await save_upload(attachment)
            orig_name = attachment.filename

        conn = get_connection(db_path)
        try:
            cur = conn.execute(
                """INSERT INTO class_updates
                   (title, message, target_level, attachment_original_name, attachment_stored_name, attachment_mime_type, posted_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (clean_title, clean_msg, target_level.strip() or "All Levels", orig_name, stored_name, mime, teacher["id"], utc_now_iso()),
            )
            conn.commit()
            row = conn.execute(
                """SELECT u_upd.id, u_upd.title, u_upd.message, u_upd.target_level,
                          u_upd.attachment_original_name, u_upd.attachment_mime_type,
                          u_upd.created_at, usr.full_name AS author_name
                   FROM class_updates u_upd
                   JOIN users usr ON usr.id = u_upd.posted_by
                   WHERE u_upd.id = ?""",
                (cur.lastrowid,),
            ).fetchone()
            return {"update": dict(row)}
        finally:
            conn.close()

    @app.get("/api/updates/{update_id}/attachment")
    def get_update_attachment(
        update_id: int,
        download: int = Query(0),
        _user: dict = Depends(require_auth),
    ):
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT attachment_original_name, attachment_stored_name, attachment_mime_type FROM class_updates WHERE id = ?",
                (update_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row or not row["attachment_stored_name"]:
            raise HTTPException(status_code=404, detail="Attachment not found")
        return build_file_response(
            row["attachment_stored_name"],
            row["attachment_original_name"],
            row["attachment_mime_type"] or "application/octet-stream",
            bool(download),
        )

    @app.delete("/api/updates/{update_id}")
    def delete_update(update_id: int, _teacher: dict = Depends(require_teacher)):
        conn = get_connection(db_path)
        try:
            row = conn.execute("SELECT attachment_stored_name FROM class_updates WHERE id = ?", (update_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Update not found")
            conn.execute("DELETE FROM class_updates WHERE id = ?", (update_id,))
            conn.commit()
            remove_stored_file(row["attachment_stored_name"])
            return {"ok": True}
        finally:
            conn.close()

    # ---- Class Schedule Routes ----

    @app.get("/api/schedule")
    def list_schedule(_user: dict = Depends(require_auth)):
        conn = get_connection(db_path)
        try:
            rows = conn.execute(
                """SELECT cs.*, u.full_name AS teacher_name
                   FROM class_schedule cs
                   JOIN users u ON u.id = cs.created_by
                   ORDER BY cs.id ASC"""
            ).fetchall()
            return {"schedule": [dict(r) for r in rows]}
        finally:
            conn.close()

    @app.post("/api/schedule", status_code=201)
    def create_schedule(payload: CreateScheduleRequest, teacher: dict = Depends(require_teacher)):
        if not payload.title.strip() or not payload.day_or_date.strip() or not payload.time_slot.strip():
            raise HTTPException(status_code=400, detail="Title, day/date, and time slot are required")
        conn = get_connection(db_path)
        try:
            cur = conn.execute(
                """INSERT INTO class_schedule
                   (title, day_or_date, time_slot, target_level, location_or_link, notes, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload.title.strip(),
                    payload.day_or_date.strip(),
                    payload.time_slot.strip(),
                    payload.target_level.strip() or "All Levels",
                    payload.location_or_link.strip(),
                    payload.notes.strip(),
                    teacher["id"],
                    utc_now_iso(),
                ),
            )
            conn.commit()
            row = conn.execute(
                """SELECT cs.*, u.full_name AS teacher_name
                   FROM class_schedule cs JOIN users u ON u.id = cs.created_by WHERE cs.id = ?""",
                (cur.lastrowid,),
            ).fetchone()
            return {"entry": dict(row)}
        finally:
            conn.close()

    @app.delete("/api/schedule/{sched_id}")
    def delete_schedule(sched_id: int, _teacher: dict = Depends(require_teacher)):
        conn = get_connection(db_path)
        try:
            cur = conn.execute("DELETE FROM class_schedule WHERE id = ?", (sched_id,))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Schedule entry not found")
            return {"ok": True}
        finally:
            conn.close()

    # Keep error format consistent with frontend `data.error || data.detail`
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()

