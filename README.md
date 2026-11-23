# ragasetu (FastAPI)
This app gives the music teachers and students to share content and updates easily

A full-stack classical music learning web application for a teacher (guru) and students across skill levels (**Beginner**, **Intermediate**, **Advanced**), built with **FastAPI**, **Uvicorn**, **SQLite**, and a responsive HTML/CSS/JavaScript frontend.

## Features

- **Login & Role-Based Access**:
  - **Teacher** (`guru` / `guru123`): Upload songs, manage students & levels, post class updates with attachments, and manage the class schedule.
  - **Students** (`ananya`, `karthik`, `divya` / `student123`): Browse & search songs, view lyrics, stream audio/thalam videos inline, download all files, and view class updates and schedules.
- **4-Component Song Structure**:
  1. **Lyrics** (inline text + downloadable file)
  2. **Full Audio Recording** (inline player + download)
  3. **Video Recording of Thalam** (inline video player + download)
  4. **Multi-Part Audio Recordings** (multiple labeled parts such as Pallavi, Anupallavi, Charanam, each playable and downloadable)
- **8 Song Classification Buckets**:
  - `Bhajan`, `Kriti`, `Carnatic - Basic`, `Carnatic - Geetham`, `Carnatic - Varnam`, `Carnatic - Keerthanai`, `Thirupugazh`, `Thevaram`
- **Class Updates & Class Schedule**: Teacher-posted announcements (with optional file attachments) and weekly/upcoming class schedules.
- **Interactive API Docs**: Available at `/docs` (Swagger UI) and `/openapi.json`.

## Setup & Running Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Then open `http://127.0.0.1:8000` in your browser.

## Running Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

