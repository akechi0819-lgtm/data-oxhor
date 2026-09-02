import json
import re
from collections import defaultdict
from datetime import date
from openpyxl import load_workbook

SOURCE = "/Users/akechi/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_7464434643712_5d13/temp/drag/20260821满班率(1).xlsx"
OUTPUT = "outputs/teacher_class_load_20260821/teacher_class_load_data.json"
EXCLUDED_KEYWORDS = ("预热", "模考", "定金", "虚拟", "校内", "辅导", "体验", "试听", "封闭", "冲刺", "强化")
AUTUMN_START = date(2026, 9, 1)
AUTUMN_END = date(2026, 11, 30)
DAY_PATTERNS = {
    "周中": re.compile(r"周(?:一|二|三|四|五)|星期(?:一|二|三|四|五)"),
    "周六": re.compile(r"周六|星期六"),
    "周日": re.compile(r"周日|星期日"),
}


def schedule_days(schedule):
    """Use term-time schedule fragments; vacation intensive sessions do not change the primary day."""
    text = str(schedule or "").replace("\n", " ")
    result = []
    for label, pattern in DAY_PATTERNS.items():
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 35):match.start()]
            vacation_position = max(prefix.rfind("暑假"), prefix.rfind("寒假"))
            term_position = max(prefix.rfind("秋季"), prefix.rfind("春季"), prefix.rfind("开学后"))
            if vacation_position > term_position:
                continue
            # A date range immediately preceding the weekday denotes an intensive block,
            # not the recurring term-time schedule (for example, "7.13-23周二至周五").
            if re.search(r"\d{1,4}(?:[./月]\d{1,2})?\s*[-至到]\s*\d{1,2}(?:[./月]\d{1,2})?\s*$", prefix.strip(" ，,：:")) and "每周" not in prefix[-10:]:
                continue
            result.append(label)
            break
    return result


def class_series(name, code):
    """Return the exact class prefix used to link a class with its renewals.

    Prefixes are never normalized: ``L301`` and ``301`` are different series.
    """
    text = str(name or "")
    # Pure numeric values are only a series when the name explicitly says 端/续;
    # this avoids treating a date label such as “0905-下午” as a series number.
    numbered = re.match(r"\s*(\d{3,4})\s*[-－]\s*(?:端|续)\s*[-－]", text)
    if numbered:
        return numbered.group(1)
    alphanumeric = re.match(r"\s*([A-Za-z]\d{3,4})\s*[-－]", text)
    return alphanumeric.group(1).upper() if alphanumeric else str(code)


workbook = load_workbook(SOURCE, read_only=True, data_only=True)
sheet = workbook.active
headers = next(sheet.iter_rows(values_only=True))
index = {header: position for position, header in enumerate(headers)}
details = []

for row in sheet.iter_rows(values_only=True):
    if row[index["班级编码"]] == "班级编码" or row[index["归属"]] not in ("青少", "初中"):
        continue
    context = " | ".join(
        str(row[index[field]])
        for field in ("课程产品备注", "班级名称（外）", "课程产品名称", "产品品类", "产品体系", "项目名称")
        if row[index[field]] not in (None, "")
    )
    if any(keyword in context for keyword in EXCLUDED_KEYWORDS):
        continue
    start_date = row[index["实际开课日期"]]
    end_date = row[index["实际结课日期"]]
    if not start_date or not end_date or start_date.date() > AUTUMN_END or end_date.date() < AUTUMN_START:
        continue
    days = schedule_days(row[index["上课时间(外)"]])
    teachers = [teacher.strip() for teacher in str(row[index["授课教师"]] or "").split(",") if teacher.strip()]
    if not teachers:
        teachers = ["未分配教师"]
    for teacher in teachers:
        details.append({
            "团队": row[index["归属"]],
            "教师": teacher,
            "班级编码": row[index["班级编码"]],
            "班级系列号": class_series(row[index["班级名称（外）"]], row[index["班级编码"]]),
            "班级名称": row[index["班级名称（外）"]],
            "课程产品": row[index["课程产品名称"]],
            "实际开课日期": start_date.date().isoformat(),
            "实际结课日期": end_date.date().isoformat(),
            "上课时间": row[index["上课时间(外)"]],
            "周中": 1 if "周中" in days else 0,
            "周六": 1 if "周六" in days else 0,
            "周日": 1 if "周日" in days else 0,
            "排课归类": "、".join(days) if days else "待确认",
        })

merged = defaultdict(list)
for item in details:
    # Same time slot alone is not evidence of the same class. Only the explicit
    # series prefix joins renewal records.
    merged[(item["团队"], item["教师"], item["班级系列号"])].append(item)

deduplicated_details = []
summary = defaultdict(lambda: {"总班数": 0, "周中": 0, "周六": 0, "周日": 0, "排课待确认": 0, "合并班号数": 0})
for items in merged.values():
    team, teacher = items[0]["团队"], items[0]["教师"]
    codes = sorted({str(item["班级编码"]) for item in items})
    # The newest class number represents the current term schedule of a continuing class.
    representative = dict(max(items, key=lambda item: (item["实际开课日期"], str(item["班级编码"]))))
    representative["首期开课日期"] = min(item["实际开课日期"] for item in items)
    representative["最近结课日期"] = max(item["实际结课日期"] for item in items)
    representative["合并班号"] = "、".join(codes)
    representative["合并班号数"] = len(codes)
    representative["排课归类"] = "、".join(field for field in ("周中", "周六", "周日") if representative[field]) or "待确认"
    deduplicated_details.append(representative)
    key = (team, teacher)
    summary[key]["总班数"] += 1
    summary[key]["合并班号数"] += len(codes)
    for field in ("周中", "周六", "周日"):
        summary[key][field] += representative[field]
    if representative["排课归类"] == "待确认":
        summary[key]["排课待确认"] += 1

summary_rows = [
    {"团队": team, "教师": teacher, **metrics}
    for (team, teacher), metrics in summary.items()
]
summary_rows.sort(key=lambda item: (item["团队"], -item["总班数"], item["教师"]))
deduplicated_details.sort(key=lambda item: (item["团队"], item["教师"], item["班级系列号"]))
with open(OUTPUT, "w", encoding="utf-8") as handle:
    json.dump({"summary": summary_rows, "details": deduplicated_details}, handle, ensure_ascii=False)
