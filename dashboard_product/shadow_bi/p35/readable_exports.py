"""Turn native table presentation trees into typed, reviewable exports."""
from __future__ import annotations

from html.parser import HTMLParser
from itertools import product
import json
import io
import numbers
import re
import unicodedata
from typing import Any

import pandas as pd


_NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?\s*%?")
_PLACEHOLDERS = {"", "—", "–", "N/A", "n/a", "null", "None"}
_METRIC_ALIASES = {
    "cash": "现金", "cash_prior": "现金同期", "cash_yoy": "现金同比",
    "cash_share": "现金占比", "orders": "工单", "orders_prior": "工单同期",
    "orders_yoy": "工单同比", "orders_share": "工单占比", "heads": "人头",
    "heads_prior": "人头同期", "heads_yoy": "人头同比", "heads_share": "人头占比",
    "spend": "花费", "expense": "花费", "same_window_expense": "同窗费用",
    "same_window_income": "同窗收入", "same_window_cash": "同窗现金",
    "same_window_orders": "同窗工单", "roi": "回收倍数", "unit_cost": "单条工单成本",
    "new_through_cutoff": "截止日新增", "classification_note": "归类说明",
    "归类说明": "归类说明", "cash_yoy": "现金同比", "prior": "同期",
    "yoy": "同比", "actual": "当期", "target": "目标", "share": "占比",
    "value": "数值", "name": "名称", "title": "名称", "label": "名称",
    "line": "业务线", "team_scope": "团队范围", "school_attribute": "学校属性",
    "attribute": "属性", "渠道": "渠道", "一级渠道": "一级渠道",
}
_LABEL_FIELDS = ("节点名称", "name", "title", "label", "名称", "学校", "渠道", "平台", "业务线", "年级", "指标")
_CHILD_KEYS = {"children", "nodes", "items", "rows", "grades", "schools", "scopes", "channels", "platforms", "attributes", "children_data"}
_DETAILS_LABELS = {
    "现金（元）": "现金", "现金": "现金", "工单": "工单", "人头": "人头",
    "花费": "花费", "本期花费": "花费", "同窗费用": "同窗费用", "同窗收入": "同窗收入",
    "回收倍数": "回收倍数", "ROI": "回收倍数", "单条工单成本": "单条工单成本",
    "现金同期": "现金同期", "工单同期": "工单同期", "人头同期": "人头同期",
    "现金同比": "现金同比", "工单同比": "工单同比", "人头同比": "人头同比",
    "同期": "同期", "同比": "同比", "现金占比": "现金占比", "工单占比": "工单占比",
    "合计工单": "合计工单", "线上工单": "线上工单", "线下工单": "线下工单",
    "待确认工单": "待确认工单", "截止日新增": "截止日新增", "同窗工单": "同窗工单",
    "归类说明": "归类说明", "classification_note": "归类说明",
}


class _Element:
    def __init__(self, tag: str, attrs: dict[str, str] | None = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[_Element | str] = []


class _TreeParser(HTMLParser):
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Element("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Element(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in self._VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(_Element(tag, {key: value or "" for key, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def _elements(node: _Element, tag: str | None = None) -> list[_Element]:
    return [child for child in node.children if isinstance(child, _Element) and (tag is None or child.tag == tag)]


def _text(node: _Element) -> str:
    return " ".join(part.strip() for child in node.children for part in ([_text(child)] if isinstance(child, _Element) else [child]) if part.strip())


def _direct_text(node: _Element) -> str:
    return " ".join(child.strip() for child in node.children if isinstance(child, str) and child.strip())


def _number(text: str) -> int | float | None:
    cleaned = text.strip().replace("−", "-")
    if cleaned in _PLACEHOLDERS:
        return None
    match = _NUMBER.fullmatch(cleaned)
    if not match:
        return None
    value = match.group().replace(",", "").replace(" ", "")
    percent = value.endswith("%")
    try:
        number = float(value[:-1] if percent else value)
    except ValueError:
        return None
    if percent:
        return number / 100
    return int(number) if number.is_integer() else number


def _number_after(pattern: str, text: str, *, percent_only: bool = False) -> int | float | None:
    match = re.search(pattern + r"\s*[:：]?\s*(—|–|[-+]?\d[\d,]*(?:\.\d+)?\s*%?)", text, re.I)
    if not match or (percent_only and not match.group(1).strip().endswith("%")):
        return None
    return _number(match.group(1))


def _metric_label(text: str) -> str | None:
    if "占本业务组工单" in text or "占本业务线工单" in text:
        return "工单占比"
    if "占本业务线现金" in text:
        return "现金占本业务线"
    if "占本渠道现金" in text:
        return "现金占本渠道"
    for label in sorted(_DETAILS_LABELS, key=len, reverse=True):
        if re.search(r"(?:^|[\s/])" + re.escape(label) + r"(?:$|[\s（(:：/])", text, re.I):
            return _DETAILS_LABELS[label]
    return None


def _extract_metrics(cell: _Element, default: str | None = None) -> dict[str, Any]:
    text = _text(cell)
    direct = _elements(cell, "span")
    label_text = _text(direct[0]) if direct else ""
    label = _metric_label(label_text) or _metric_label(text) or default
    strong_values = [_text(item) for item in cell.children if isinstance(item, _Element) and item.tag == "strong"]
    if not strong_values:
        strong_values = [_text(item) for item in _descendants(cell, "strong")]
    fields: dict[str, Any] = {}
    fields.update(_labeled_strong_pairs(cell))

    if label == "归类说明" or "classification_note" in text.lower() or "归类说明" in text:
        strong_note = next((value for value in strong_values if value), "")
        note = strong_note or re.sub(r"^.*?(?:classification_note|归类说明)\s*[:：]?\s*", "", text, flags=re.I).strip()
        if note and note != text:
            fields["归类说明"] = note
        elif strong_note:
            fields["归类说明"] = strong_note
        return fields

    # Composite groups are explicitly labeled in the HTML, so their values are
    # numeric presentation values rather than arbitrary numeric-looking text.
    if "同窗投入 / 收入" in text or "同窗投入/收入" in text:
        values = _pair_values(strong_values)
        for key, value in zip(("同窗费用", "同窗收入"), values):
            fields[key] = value
    elif "本期工单 / 现金" in text or "本期工单/现金" in text:
        values = _pair_values(strong_values)
        for key, value in zip(("工单", "现金"), values):
            fields[key] = value
    elif label:
        value = _number(strong_values[0]) if strong_values else _number_after(re.escape(label), text)
        if value is not None or (strong_values and strong_values[0].strip() in _PLACEHOLDERS):
            fields[label] = value

    # Period, growth, and share labels are rendered as text in the current
    # native tables. Parse them only in their labeled HTML metric context.
    for metric in ("现金", "工单", "人头"):
        explicit = bool(re.search(metric + r"(?:同期|同比)", text))
        is_this_metric = label == metric or explicit
        if not is_this_metric:
            continue
        prior_pattern = re.escape(metric) + r"同期" if explicit else r"同期"
        prior = _number_after(prior_pattern, text)
        if prior is not None:
            fields[metric + "同期"] = prior
        yoy_pattern = re.escape(metric) + r"同比" if explicit else r"同比"
        yoy = _number_after(yoy_pattern, text, percent_only=True)
        if yoy is None and prior is not None:
            context_pattern = re.escape(metric) + r"同期[^·]*·" if explicit else r"同期[^·]*·"
            yoy = _number_after(context_pattern, text, percent_only=True)
            if yoy is None and not explicit:
                yoy = _number_after(r"·", text, percent_only=True)
        if yoy is not None:
            fields[metric + "同比"] = yoy
    for phrase, key in (("占本业务线现金", "现金占本业务线"), ("占本渠道现金", "现金占本渠道"),
                        ("占本业务组工单", "工单占比"), ("占本业务线工单", "工单占比")):
        share = _number_after(re.escape(phrase), text, percent_only=True)
        if share is not None:
            fields[key] = share
    if "占比" in text:
        share = _number_after("占比", text, percent_only=True)
        if share is not None and label in {"现金", "工单", "人头"}:
            fields[label + "占比"] = share
    for key in ("截止日新增", "同窗工单"):
        value = _number_after(re.escape(key), text)
        if key in text:
            fields[key] = value
    if label == "回收倍数" and "单条成本" in text:
        unit_cost = _number_after("单条成本", text)
        if unit_cost is not None:
            fields["单条工单成本"] = unit_cost
    roi = _number_after("ROI", text)
    if "ROI" in text:
        fields["回收倍数"] = roi
    unit_cost = _number_after("单条成本", text)
    if "单条成本" in text:
        fields["单条工单成本"] = unit_cost
    return fields


def _number_matches(text: str) -> list[int | float]:
    values = []
    for match in _NUMBER.finditer(text):
        value = _number(match.group())
        if value is not None:
            values.append(value)
    return values


def _pair_values(strong_values: list[str]) -> list[int | float | None]:
    if len(strong_values) >= 2:
        return [_number(value) for value in strong_values[:2]]
    text = " ".join(strong_values)
    parts = re.split(r"\s*/\s*", text, maxsplit=1)
    if len(parts) == 2:
        return [_number(part) for part in parts]
    return _number_matches(text)[:2]


def _labeled_strong_pairs(cell: _Element) -> dict[str, Any]:
    """Read adjacent label/value pairs, including several pairs in one cell."""
    fields: dict[str, Any] = {}
    for index, child in enumerate(cell.children):
        if not isinstance(child, _Element) or child.tag != "span":
            continue
        label = _metric_label(_text(child))
        if not label:
            continue
        for following in cell.children[index + 1:]:
            if isinstance(following, str) and not following.strip():
                continue
            if not isinstance(following, _Element):
                break
            if following.tag == "strong":
                text = _text(following)
                value = _number(text)
                if value is not None or text.strip() in _PLACEHOLDERS:
                    fields[label] = value
            break
    return fields


def _descendants(node: _Element, tag: str):
    for child in node.children:
        if isinstance(child, _Element):
            if child.tag == tag:
                yield child
            yield from _descendants(child, tag)


def _row_fields(node: _Element, source: str) -> tuple[str, list[str], dict[str, Any]] | None:
    cells = _elements(node, "span")
    if not cells:
        return None
    title = cells[0]
    name = _direct_text(title)
    nested = _elements(title, "span")
    attributes: list[str] = []
    fields: dict[str, Any] = {}
    paired_note_index: int | None = None
    for index, item in enumerate(nested):
        value = _text(item)
        if not value:
            continue
        if index == paired_note_index:
            continue
        if "classification_note" in value.lower() or "归类说明" in value:
            detail = _extract_metrics(item)
            fields.update(detail)
            if "归类说明" not in fields and index + 1 < len(nested):
                fields["归类说明"] = _text(nested[index + 1])
                paired_note_index = index + 1
        elif re.match(r"本期花费\b", value):
            fields.update(_extract_metrics(item, "花费"))
        else:
            attributes.append(value)
    defaults = {
        "学校表现": ("现金", "工单", "人头"), "渠道表现": ("现金", "工单", "人头"),
        "费用与回收": ("花费", "回收倍数", "单条工单成本"),
        "平台投入产出": (), "条线工单": (),
    }.get(source, ())
    for index, cell in enumerate(cells[1:]):
        default = defaults[index] if index < len(defaults) else None
        fields.update(_extract_metrics(cell, default))
    for attr, value in node.attrs.items():
        if attr in {"data-classification-note", "classification_note"} and value:
            fields["归类说明"] = value
    return name, attributes, fields


def _html_nodes(value: str, source: str) -> list[dict[str, Any]]:
    parser = _TreeParser()
    parser.feed(value)
    result: list[dict[str, Any]] = []

    def visit(container: _Element, parent_path: tuple[str, ...]) -> None:
        if container.tag == "details":
            summary = next(iter(_elements(container, "summary")), None)
            parsed = _row_fields(summary, source) if summary else None
            if parsed:
                name, attrs, metrics = parsed
                parent_path = parent_path + (name,)
                result.append({"树来源": source, "层级": len(parent_path) - 1,
                              "父级路径": " / ".join(parent_path[:-1]) or None,
                              "节点名称": name, "节点属性": " / ".join(attrs) or None,
                              "节点类型": "层级节点", **metrics})
        elif container.tag in {"div", "section", "li"}:
            parsed = _row_fields(container, source)
            if parsed:
                name, attrs, metrics = parsed
                path = parent_path + (name,)
                result.append({"树来源": source, "层级": len(path) - 1, "父级路径": " / ".join(parent_path) or None,
                              "节点名称": name, "节点属性": " / ".join(attrs) or None,
                              "节点类型": "明细节点", **metrics})
                parent_path = path
        for child in _elements(container):
            if child.tag == "summary":
                continue
            if child.tag in {"details", "div", "section", "li"}:
                visit(child, parent_path)

    visit(parser.root, ())
    return result


def _json_label(item: dict[str, Any]) -> tuple[str, str] | None:
    for key in _LABEL_FIELDS:
        if key in item and isinstance(item[key], (str, int, float)):
            return key, str(item[key])
    return None


def _json_key(key: str) -> str:
    return _METRIC_ALIASES.get(key, key)


def _json_scalar_fields(value: Any, path: tuple[str, ...] = ()) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _LABEL_FIELDS or key in _CHILD_KEYS:
                continue
            fields.update(_json_scalar_fields(child, path + (key,)))
        return fields
    if isinstance(value, list):
        return fields
    if not path:
        return fields
    aliases = {"actual": "", "current": "", "value": "", "prior": "同期", "previous": "同期",
               "yoy": "同比", "growth": "同比", "share": "占比", "target": "目标"}
    metric_keys = {"cash", "orders", "heads", "spend", "expense", "roi", "unit_cost"}
    metric_parent = next((key for key in reversed(path[:-1]) if key in metric_keys), None)
    if metric_parent and path[-1] in aliases:
        base = _json_key(metric_parent)
        suffix = aliases[path[-1]]
        name = base + suffix
    else:
        name = _json_key(path[-1])
    fields[name] = value
    return fields


def _json_nodes(value: Any, source: str) -> list[dict[str, Any]]:
    if not isinstance(value, (dict, list)):
        return []
    result: list[dict[str, Any]] = []

    def walk(item: Any, parent_path: tuple[str, ...], edge: str | None = None) -> bool:
        if isinstance(item, list):
            found = False
            for child in item:
                found = walk(child, parent_path, edge) or found
            return found
        if not isinstance(item, dict):
            return False
        label_pair = _json_label(item)
        if not label_pair and not parent_path:
            found = False
            for key, child in item.items():
                if isinstance(child, (dict, list)):
                    found = walk(child, (), _json_key(key)) or found
            return found
        label_key, name = label_pair or ("", edge or "结构")
        path = parent_path + (name,)
        attrs = []
        fields: dict[str, Any] = {}
        children = []
        for key, child in item.items():
            if key == label_key:
                continue
            mapped = _json_key(key)
            if key in _CHILD_KEYS or (isinstance(child, list) and any(isinstance(element, dict) for element in child)):
                children.append((key, child))
            elif isinstance(child, dict):
                if _json_label(child):
                    children.append((key, child))
                else:
                    fields.update(_json_scalar_fields(child, (key,)))
            elif key in {"line", "team_scope", "school_attribute", "attribute", "一级渠道"} and child is not None:
                attrs.append(str(child))
            elif key in {"classification_note", "归类说明"}:
                fields["归类说明"] = child
            elif isinstance(child, list):
                fields[mapped] = " / ".join(str(value) for value in child)
            elif isinstance(child, (str, int, float, bool)) or child is None:
                fields[mapped] = child
        result.append({"树来源": source, "层级": len(path) - 1, "父级路径": " / ".join(path[:-1]) or None,
                       "节点名称": name, "节点属性": " / ".join(attrs) or None,
                       "节点类型": "层级节点" if children else "明细节点", **fields})
        for key, child in children:
            walk(child, path, _json_key(key))
        return True

    walk(value, ())
    return result


def _candidate(value: Any, source: str) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(value, str):
        return [], False
    stripped = value.strip()
    if "<details" in stripped.lower() or ("<div" in stripped.lower() and "<span" in stripped.lower()):
        return _html_nodes(stripped, source), True
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [], False
        nodes = _json_nodes(parsed, source)
        return nodes, bool(nodes)
    return [], False


def readable_export_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Expand a single or multiple HTML/JSON presentation cells into typed tree rows."""
    sources: dict[str, list[list[dict[str, Any]]]] = {}
    for column in df.columns:
        values = []
        found = False
        for value in df[column].tolist():
            records, candidate = _candidate(value, str(column))
            values.append(records)
            found = found or candidate
        if found and any(values):
            sources[column] = values
    if not sources:
        return df

    structured_columns = list(sources)
    base_columns = [column for column in df.columns if column not in sources]
    renamed_base = {column: _METRIC_ALIASES.get(str(column), column) for column in base_columns}
    multiple = len(structured_columns) > 1
    output: list[dict[str, Any]] = []
    for position, row in enumerate(df.to_dict(orient="records")):
        choices = []
        for column in structured_columns:
            records = sources[column][position]
            choices.append(records or [{"树来源": column, "层级": 0, "父级路径": None,
                                        "节点名称": None, "节点属性": None, "节点类型": "无层级内容"}])
        for selected in product(*choices):
            record = {renamed_base[column]: row[column] for column in base_columns}
            for source, node in zip(structured_columns, selected):
                for key, value in node.items():
                    name = f"{source} · {key}" if multiple else key
                    record[name] = value
            output.append(record)
    return pd.DataFrame.from_records(output)


def _xlsx_number_format(header: str, metric_label: str) -> str | None:
    if any(token in header for token in ("同比", "占比", "进度", "完成率")):
        return "0.0%"
    if any(token in header for token in ("现金", "花费", "费用", "收入", "成本", "金额", "投入")):
        return "#,##0.00"
    if header in {"当期", "同期", "目标", "目标差额", "呈现"}:
        if "现金" in metric_label:
            return "#,##0.00"
        if any(token in metric_label for token in ("工单", "人头", "人数")):
            return "#,##0.##"
    if any(token in header for token in ("工单", "人头", "人数", "数量", "新增", "目标")):
        return "#,##0.##"
    return None


def _display_width(value: Any) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in str(value))


def _format_xlsx_export(content: Any) -> Any:
    """Apply readable worksheet layout after Superset's native XLSX serialization."""
    if not isinstance(content, (bytes, bytearray)):
        return content

    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = load_workbook(io.BytesIO(content))
    header_fill = PatternFill(fill_type="solid", fgColor="DCEAF7")
    header_font = Font(bold=True, color="17365D")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        if sheet.max_row < 1 or sheet.max_column < 1:
            continue
        for cell in sheet[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
        sheet.row_dimensions[1].height = 24

        headers = [str(sheet.cell(1, column).value or "") for column in range(1, sheet.max_column + 1)]
        metric_column = next((index + 1 for index, header in enumerate(headers) if header in {"指标", "统计指标"}), None)
        for column, header in enumerate(headers, start=1):
            width = max((_display_width(sheet.cell(row, column).value if sheet.cell(row, column).value is not None else "")
                         for row in range(1, sheet.max_row + 1)), default=0)
            sheet.column_dimensions[sheet.cell(1, column).column_letter].width = min(max(width + 2, 10), 48)
            for row in range(2, sheet.max_row + 1):
                cell = sheet.cell(row, column)
                if isinstance(cell.value, numbers.Real) and not isinstance(cell.value, bool):
                    metric_label = str(sheet.cell(row, metric_column).value or "") if metric_column else ""
                    number_format = _xlsx_number_format(header, metric_label)
                    if number_format:
                        cell.number_format = number_format

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _dataset_ids_from_manifest(config: Any) -> set[str]:
    datasets = config.get("datasets", {})
    visible = config.get("charts", {})
    if not isinstance(datasets, dict) or not isinstance(visible, dict):
        return set()
    return {str(datasets[key]) for key in visible if key in datasets}


def _visible_dataset_ids() -> set[str]:
    from dashboard_product.shadow_bi.p3.catalog import AUDIT

    manifest = AUDIT.parent / "shadow-bi-p35-20261023" / "native-bootstrap.json"
    try:
        config = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    return _dataset_ids_from_manifest(config)


def install_readable_exports() -> None:
    """Wrap the Superset export serializer without changing JSON chart responses."""
    from functools import wraps

    from superset.common.chart_data import ChartDataResultFormat
    from superset.common.query_context_processor import QueryContextProcessor
    from superset.utils.core import extract_dataframe_dtypes

    visible_ids = _visible_dataset_ids()
    original = QueryContextProcessor.get_data
    if getattr(original, "_shadow_readable_exports", False):
        return

    @wraps(original)
    def readable_get_data(self, df, coltypes):
        query_context = self._query_context
        datasource_id = getattr(self._qc_datasource, "id", None)
        if (query_context.result_format in {ChartDataResultFormat.CSV, ChartDataResultFormat.XLSX}
                and str(datasource_id) in visible_ids):
            converted = readable_export_dataframe(df)
            if converted is not df:
                coltypes = extract_dataframe_dtypes(converted, self._qc_datasource)
                df = converted
        result = original(self, df, coltypes)
        if (query_context.result_format == ChartDataResultFormat.CSV
                and str(datasource_id) in visible_ids and not result.startswith('\ufeff')):
            return '\ufeff' + result
        if (query_context.result_format == ChartDataResultFormat.XLSX
                and str(datasource_id) in visible_ids):
            return _format_xlsx_export(result)
        return result

    readable_get_data._shadow_readable_exports = True
    QueryContextProcessor.get_data = readable_get_data
