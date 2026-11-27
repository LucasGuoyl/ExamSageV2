"""Exercise both entry points and the original pages actually served to students."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile
import pytest

from examsage import study_host
from examsage.student_workspace import Principal, StudentWorkspace
from examsage.study_window import StudyDesk
from test_study_host import command


def test_english_launcher_opens_translated_lesson_and_preserves_chinese_course(tmp_path):
    from test_student_distribution import ROOT, PYTHON, run
    import os
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if k in os.environ}
    archive = tmp_path / "student.zip"
    run([PYTHON, "-I", "-B", ROOT/"tools/build_student_kit.py", archive], env)
    with ZipFile(archive) as kit:
        assert b"study --language en" in kit.read("Start ExamSage.bat")
        assert b"kit.py\" study" in kit.read("开始学习.bat")
        assert "STUDENT-GUIDE.txt" in kit.namelist()
        for subject in ("physics", "mathematics", "literature", "history"):
            base = f"examples/course-packs-en/{subject}/"
            manifest = json.loads(kit.read(base + "pack.json"))["manifest"]
            for doc in manifest["documents"]:
                assert sha256(kit.read(base + doc["relative_path"])).hexdigest() == doc["sha256"]
    workspace = StudentWorkspace(tmp_path/"workspace", Principal("student", frozenset()))
    with closing(StudyDesk(workspace)) as desk:
        studio = study_host.Studio(desk)
        english = command(studio, studio.request({"action":"state"}), "example", language="en")
        assert english["courses"][0]["name"] == "Physics example · Linear spring"
        doc = desk.store.manifest(desk._current()).documents[0]
        first = desk.store.get(desk._current(), doc.id + ":p1").details["raw_text"]
        assert "200 N/m" in first and "spring" in first.lower()
        chinese = command(studio, english, "example", language="zh")
        assert len(chinese["courses"]) == 2 and chinese["course_id"] != english["course_id"]
        again = command(studio, chinese, "example", language="en")
        assert again["course_id"] == english["course_id"] and len(again["courses"]) == 2


def test_both_studio_entry_urls_serve_the_app_and_only_known_assets():
    for path in ("/en/", "/zh/"):
        mime, body = study_host._asset(path)
        assert "text/html" in mime and b'language' in body
    assert study_host._asset("/studio-locale.js")[0] == "text/javascript"
    assert study_host._asset("/en/../student_kit/kit.py") is None


def test_english_launcher_explains_an_unavailable_running_workspace(tmp_path, monkeypatch):
    workspace = StudentWorkspace(tmp_path/"workspace", Principal("student", frozenset()))
    def busy(workspace):
        raise study_host.StudentServerBusy("当前学生的学习服务已经打开，请使用已打开的窗口。")
    monkeypatch.setattr(study_host, "StudyDesk", busy)
    with pytest.raises(study_host.StudentServerBusy, match="already open"):
        study_host.open_studio(workspace=workspace, language="en")
