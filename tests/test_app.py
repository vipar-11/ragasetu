"""End-to-end integration tests for the FastAPI ragasetu application."""

import os
import shutil
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from db import SONG_CATEGORIES


class RagasetuFastAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ragasetu_fastapi_test_")
        self.app = create_app(data_dir=self.tmp_dir)
        self.teacher = TestClient(self.app)
        self.student = TestClient(self.app)
        self.anon = TestClient(self.app)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_unauthenticated_blocked(self):
        for path in ("/api/songs", "/api/updates", "/api/schedule", "/api/users"):
            resp = self.anon.get(path)
            self.assertEqual(resp.status_code, 401, f"Expected 401 for {path}")

    def test_static_index_and_openapi_docs(self):
        resp = self.anon.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ragasetu", resp.text)

        docs = self.anon.get("/openapi.json")
        self.assertEqual(docs.status_code, 200)

    def test_full_teacher_and_student_workflow(self):
        # 1. Login as student & verify read-only access
        resp = self.student.post("/api/login", json={"username": "ananya", "password": "student123"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user"]["role"], "student")
        self.assertEqual(resp.json()["user"]["level"], "Beginner")

        self.assertEqual(self.student.get("/api/songs").status_code, 200)
        self.assertEqual(
            self.student.post(
                "/api/schedule", json={"title": "Hack", "day_or_date": "Mon", "time_slot": "5pm"}
            ).status_code,
            403,
        )
        self.assertEqual(self.student.get("/api/users").status_code, 403)

        # 2. Login as teacher
        resp = self.teacher.post("/api/login", json={"username": "guru", "password": "guru123"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user"]["role"], "teacher")

        # 3. Create a new student
        resp = self.teacher.post(
            "/api/users",
            json={
                "username": "rohan",
                "full_name": "Rohan Sharma",
                "role": "student",
                "level": "Intermediate",
                "password": "pass123",
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["user"]["level"], "Intermediate")

        # 4. Upload a song with all 4 components
        lyrics_bytes = b"Pallavi: Vatapi Ganapatim Bhaje"
        full_audio_bytes = b"FAKE_MP3_FULL_AUDIO_DATA"
        thalam_video_bytes = b"FAKE_MP4_THALAM_VIDEO_DATA"
        part1_bytes = b"FAKE_MP3_PART_1"
        part2_bytes = b"FAKE_MP3_PART_2"

        resp = self.teacher.post(
            "/api/songs",
            data={
                "title": "Vatapi Ganapatim Bhaje",
                "category": "Kriti",
                "ragam": "Hamsadhwani",
                "thalam": "Adi",
                "composer": "Muthuswami Dikshitar",
                "target_level": "Intermediate",
                "lyrics_text": "Vatapi Ganapatim Bhaje Ham",
                "multipart_label": ["Pallavi", "Charanam"],
            },
            files=[
                ("lyrics_file", ("vatapi_lyrics.txt", lyrics_bytes, "text/plain")),
                ("full_audio", ("vatapi_full.mp3", full_audio_bytes, "audio/mpeg")),
                ("thalam_video", ("vatapi_thalam.mp4", thalam_video_bytes, "video/mp4")),
                ("multipart_audio", ("vatapi_pallavi.mp3", part1_bytes, "audio/mpeg")),
                ("multipart_audio", ("vatapi_charanam.mp3", part2_bytes, "audio/mpeg")),
            ],
        )
        self.assertEqual(resp.status_code, 201)
        song = resp.json()["song"]
        self.assertEqual(song["category"], "Kriti")
        self.assertEqual(len(song["files"]), 5)

        # 5. Verify all 8 categories are accepted and invalid category is rejected
        self.assertEqual(len(SONG_CATEGORIES), 8)
        for cat in SONG_CATEGORIES:
            r = self.teacher.post("/api/songs", data={"title": f"Sample {cat}", "category": cat})
            self.assertEqual(r.status_code, 201, f"Category {cat} should be accepted")

        r_bad = self.teacher.post("/api/songs", data={"title": "Bad", "category": "Rock"})
        self.assertEqual(r_bad.status_code, 400)

        # 6. Student views & downloads all 4 component files
        detail = self.student.get(f"/api/songs/{song['id']}").json()["song"]
        files_by_type = {}
        for f in detail["files"]:
            files_by_type.setdefault(f["component_type"], []).append(f)

        self.assertEqual(len(files_by_type["lyrics"]), 1)
        self.assertEqual(len(files_by_type["full_audio"]), 1)
        self.assertEqual(len(files_by_type["thalam_video"]), 1)
        self.assertEqual(len(files_by_type["multipart_audio"]), 2)

        for fid, expected in [
            (files_by_type["lyrics"][0]["id"], lyrics_bytes),
            (files_by_type["full_audio"][0]["id"], full_audio_bytes),
            (files_by_type["thalam_video"][0]["id"], thalam_video_bytes),
            (files_by_type["multipart_audio"][0]["id"], part1_bytes),
            (files_by_type["multipart_audio"][1]["id"], part2_bytes),
        ]:
            dl = self.student.get(f"/api/files/{fid}?download=1")
            self.assertEqual(dl.status_code, 200)
            self.assertIn("attachment", dl.headers.get("content-disposition", ""))
            self.assertEqual(dl.content, expected)

        # 7. Teacher posts class update with attachment & schedule entry
        att_bytes = b"Practice at 60 BPM"
        u_resp = self.teacher.post(
            "/api/updates",
            data={"title": "Weekend Practice", "message": "Focus on Adi thalam", "target_level": "All Levels"},
            files={"attachment": ("notes.txt", att_bytes, "text/plain")},
        )
        self.assertEqual(u_resp.status_code, 201)
        upd_id = u_resp.json()["update"]["id"]

        dl_att = self.student.get(f"/api/updates/{upd_id}/attachment?download=1")
        self.assertEqual(dl_att.status_code, 200)
        self.assertEqual(dl_att.content, att_bytes)

        s_resp = self.teacher.post(
            "/api/schedule",
            json={
                "title": "Kriti Practice",
                "day_or_date": "Every Friday",
                "time_slot": "7:00 PM - 8:00 PM",
                "target_level": "Intermediate",
            },
        )
        self.assertEqual(s_resp.status_code, 201)

        sched_list = self.student.get("/api/schedule").json()["schedule"]
        self.assertTrue(any(e["title"] == "Kriti Practice" for e in sched_list))


if __name__ == "__main__":
    unittest.main()

