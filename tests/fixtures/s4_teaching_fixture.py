from __future__ import annotations

import hashlib
import json
from pathlib import Path

from openpyxl import Workbook


def _write_schedule(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "排课记录"
    sheet.append(["S4 脱敏排课样例"])
    sheet.append([])
    sheet.append(["记录ID", "教师", "课程", "上课日期", "课时", "授课方式"])
    sheet.append(["R001", "教师甲", "英语阅读", "2027-01-05", 2, "线下"])
    sheet.append(["R002", "教师乙", "英语写作", "2027-01-06", 1.5, "直播"])
    sheet.append(["R003", "教师甲", "英语口语", "2027-01-12", 2, "线下"])
    workbook.save(path)


def _write_priority(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "教师优先级"
    sheet.append(["教师", "优先级", "适用课程"])
    sheet.append(["教师甲", 1, "英语阅读"])
    sheet.append(["教师乙", 2, "英语写作"])
    workbook.save(path)


def _write_study_abroad_schedule(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "留学预备排课"
    sheet.append(["S4 脱敏留学预备排课样例"])
    sheet.append([])
    sheet.append(["记录ID", "教师", "课程", "上课日期", "课时", "授课方式"])
    sheet.append(["A001", "教师丙", "学术写作", "2027-01-07", 2, "线上"])
    sheet.append(["A002", "教师甲", "学术阅读", "2027-01-14", 1.5, "线下"])
    workbook.save(path)


def build_s4_teaching_fixture(root: Path) -> tuple[Path, list[str]]:
    """Create deterministic, de-identified teaching workbooks for tests only."""
    schedule = root / "schedule_main.xlsx"
    study_abroad_schedule = root / "schedule_study_abroad.xlsx"
    priority = root / "teacher_priority.xlsx"
    _write_schedule(schedule)
    _write_study_abroad_schedule(study_abroad_schedule)
    _write_priority(priority)
    sources = {
        "schedule_main": {
            "filename": schedule.name,
            "sha256": hashlib.sha256(schedule.read_bytes()).hexdigest(),
        },
        "schedule_study_abroad": {
            "filename": study_abroad_schedule.name,
            "sha256": hashlib.sha256(study_abroad_schedule.read_bytes()).hexdigest(),
        },
        "teacher_priority": {
            "filename": priority.name,
            "sha256": hashlib.sha256(priority.read_bytes()).hexdigest(),
        },
    }
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"sources": sources}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    bindings = [
        f"schedule_main={schedule}",
        f"schedule_study_abroad={study_abroad_schedule}",
        f"teacher_priority={priority}",
    ]
    return manifest, bindings
