"""图表消费字段字典：把图表侧和看板侧都要用的字段元数据收拢到一处。

同一个显示名（例如「等级」）可能同时出现在售价图和标签图里：前者是能参与聚合的
数值列，后者只是字符串标签。图表行本身只存了显示名，配置方没法从元数据分辨，
所以这里按「来源 + 图表编号 + 字段名」生成字典条目，并在条目上给出类型、别名和
可聚合/可求和的判定。

看板的横轴绑定只从这份字典解析，不再自己猜字段类型；绑定里保留调用方提交时的
原始字段名（历史看板可能仍引用更正前的旧名），解析结果另外记录当前字段名。
"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

NUMERIC_HINTS = (
    "售价", "价格", "金额", "数量", "数值", "度量", "指标", "销售额", "收入",
    "利润", "成本", "销量", "次数", "时长", "占比", "比率", "率",
)
TEXT_HINTS = ("标签", "字符", "文本", "维度", "分类", "名称", "描述", "明细")
NON_ADDITIVE_AGGREGATIONS = (
    "计数", "去重计数", "平均", "均值", "最大值", "最小值", "中位数", "方差", "标准差",
)
NUMERIC_TYPE_WORDS = ("数值", "数字", "number", "numeric", "int", "float", "整数", "小数", "decimal")
TEXT_TYPE_WORDS = ("字符", "字符串", "文本", "text", "string", "标签", "维度", "category")

UNBOUND_UNKNOWN = "名称不明"
UNBOUND_COLLISION = "名称碰撞"
UNBOUND_MISMATCH = "图表与字段来源不匹配"
REVIEW_PENDING = "待复核"

_ALIAS_KEYS = (
    "别名", "字段别名", "坐标字段别名", "旧字段名", "历史字段名", "曾用名", "原字段名",
)
_METADATA_KEYS = (
    "字段列表", "消费字段", "字段定义",
    "坐标字段类型", "字段类型", "坐标字段别名", "字段别名", "旧字段名", "曾用名",
    "字段更正", "字段别名映射", "示例值",
)

# 看板确认关系、待复核项属于运行期状态，不塞进 store 的业务模块表，
# 避免 /api/overview 的模块统计因为内部表而改变。
_BINDING_LOCK = threading.RLock()
_BINDINGS: dict[str, list[dict[str, Any]]] = {}
_REVIEWS: list[dict[str, Any]] = []


def _text(value: Any) -> str:
    """把单元格值转成可比较的文本，None 统一当成空串。"""
    return "" if value is None else str(value).strip()


def _as_list(value: Any) -> list[str]:
    """兼容「分隔符字符串」和「列表」两种写法，保持原顺序去重。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = [str(item) for item in value]
    else:
        text = str(value)
        for sep in ("，", ",", "、", ";", "；", "|", "/"):
            text = text.replace(sep, "\n")
        raw = text.splitlines()
    result: list[str] = []
    for item in raw:
        item = item.strip()
        if item and item not in result:
            result.append(item)
    return result


def _normalise_type(value: Any) -> str:
    text = _text(value)
    lowered = text.lower()
    if not text:
        return ""
    if lowered in NUMERIC_TYPE_WORDS or any(word in text for word in ("数值", "数字", "整数", "小数")):
        return "数值"
    if lowered in TEXT_TYPE_WORDS or any(word in text for word in ("字符", "文本", "字符串", "标签", "维度")):
        return "字符"
    return text


def _field_type(chart: dict[str, Any], field: dict[str, Any]) -> str:
    """字段类型：显式声明优先，其次看图表类型，再看示例值，最后看字段名。"""
    for key in ("类型", "字段类型", "数据类型", "坐标字段类型"):
        normalised = _normalise_type(field.get(key))
        if normalised:
            return normalised
    for key in ("坐标字段类型", "字段类型"):
        normalised = _normalise_type(chart.get(key))
        if normalised:
            return normalised

    chart_type = _text(chart.get("图表类型"))
    if any(hint in chart_type for hint in TEXT_HINTS):
        return "字符"
    if any(hint in chart_type for hint in NUMERIC_HINTS):
        return "数值"

    samples = _as_list(field.get("示例值") or chart.get("示例值"))
    if samples:
        try:
            for sample in samples:
                float(sample)
            return "数值"
        except (TypeError, ValueError):
            return "字符"

    field_name = _text(field.get("字段名"))
    if any(hint in field_name for hint in NUMERIC_HINTS):
        return "数值"
    if any(hint in field_name for hint in TEXT_HINTS):
        return "字符"
    # 判断不了时按字符处理：字符列不会被误标成可求和。
    return "字符"


def _aggregation_flags(
    field_type: str, aggregation: str, field: dict[str, Any],
) -> tuple[bool, bool]:
    """返回 (可聚合, 可求和)。字符列两者都为否；数值列按聚合方式判断可求和。"""
    if field_type != "数值":
        can_aggregate, can_sum = False, False
    else:
        can_aggregate = True
        can_sum = not any(word in _text(aggregation) for word in NON_ADDITIVE_AGGREGATIONS)
    if "可聚合" in field:
        can_aggregate = bool(field.get("可聚合"))
    if "可求和" in field:
        can_sum = bool(field.get("可求和"))
    return can_aggregate, can_sum


def _source_of(chart: dict[str, Any], chart_code: str) -> str:
    """字典里的「来源」：优先数据来源，没有时退回图表编号。"""
    return _text(chart.get("数据来源") or chart.get("来源")) or chart_code


def _aliases_of(
    chart: dict[str, Any], field: dict[str, Any], field_name: str,
) -> list[str]:
    aliases: list[str] = []
    sources: list[Any] = [field.get(key) for key in _ALIAS_KEYS]
    sources.extend(chart.get(key) for key in _ALIAS_KEYS)

    # 字段更正既支持 {"旧字段名": "新字段名"} 这种映射，也支持
    # [{"旧": "等级", "新": "售价等级"}] 这种列表。
    corrections = chart.get("字段更正") or chart.get("字段别名映射")
    if isinstance(corrections, dict):
        for old_name, new_name in corrections.items():
            if _text(new_name) == field_name:
                sources.append(old_name)
    elif isinstance(corrections, list):
        for item in corrections:
            if not isinstance(item, dict):
                continue
            new_name = item.get("新") or item.get("新字段名") or item.get("字段名")
            old_name = item.get("旧") or item.get("旧字段名") or item.get("历史字段名")
            if _text(new_name) == field_name:
                sources.append(old_name)

    for value in sources:
        for alias in _as_list(value):
            if alias and alias != field_name and alias not in aliases:
                aliases.append(alias)
    return aliases


def _field_declarations(chart: dict[str, Any]) -> list[dict[str, Any]]:
    """列出图表声明的字段，兼容只写坐标字段的旧配置。"""
    declarations: list[dict[str, Any]] = []
    raw_fields = chart.get("字段列表") or chart.get("消费字段") or chart.get("字段定义")
    if isinstance(raw_fields, list):
        for raw in raw_fields:
            if isinstance(raw, dict):
                declaration = dict(raw)
            elif _text(raw):
                declaration = {"字段名": _text(raw)}
            else:
                continue
            if not _text(declaration.get("字段名") or declaration.get("坐标字段")):
                continue
            declaration.setdefault("字段名", declaration.get("坐标字段"))
            declarations.append(declaration)

    coordinate = _text(chart.get("坐标字段") or chart.get("字段名"))
    if coordinate and not any(_text(item.get("字段名")) == coordinate for item in declarations):
        declaration: dict[str, Any] = {"字段名": coordinate}
        for key in _METADATA_KEYS:
            if chart.get(key) is not None:
                declaration[key] = chart.get(key)
        # 图表级别的聚合方式也是这个坐标字段的聚合方式。
        if chart.get("聚合方式") is not None:
            declaration.setdefault("聚合方式", chart.get("聚合方式"))
        declarations.append(declaration)
    return declarations


def build_field_dictionary() -> list[dict[str, Any]]:
    """按图表样例数据生成消费字段字典，保持图表与字段的声明顺序。"""
    entries: list[dict[str, Any]] = []
    for chart in store.rows("chart"):
        chart_id = int(chart.get("id", 0))
        chart_code = _text(chart.get("图表编号")) or str(chart_id)
        chart_name = _text(chart.get("图表名称"))
        chart_type = _text(chart.get("图表类型"))
        source = _source_of(chart, chart_code)

        for field in _field_declarations(chart):
            field_name = _text(field.get("字段名") or field.get("坐标字段"))
            if not field_name:
                continue
            field_type = _field_type(chart, field)
            aggregation = _text(field.get("聚合方式") or chart.get("聚合方式"))
            can_aggregate, can_sum = _aggregation_flags(field_type, aggregation, field)
            entries.append({
                "来源": source,
                "字段名": field_name,
                "别名": _aliases_of(chart, field, field_name),
                "类型": field_type,
                "可聚合": can_aggregate,
                "可求和": can_sum,
                "可运算": can_aggregate,
                "图表编号": chart_code,
                "图表名称": chart_name,
                "图表类型": chart_type,
                "聚合方式": aggregation,
            })
    return entries


def _entry_identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    """判断是否同一字段时使用「来源 + 图表编号 + 字段名」，同名字段不跨来源合并。"""
    return (
        _text(entry.get("来源")),
        _text(entry.get("图表编号")),
        _text(entry.get("字段名")),
    )


def find_field_candidates(name: str) -> list[dict[str, Any]]:
    """按显示名或别名找候选字段，返回的候选不做跨来源合并。"""
    needle = _text(name)
    if not needle:
        return []
    return [
        entry for entry in build_field_dictionary()
        if entry["字段名"] == needle or needle in entry["别名"]
    ]


def list_field_dictionary(
    *,
    keyword: str | None = None,
    field_type: str | None = None,
    source: str | None = None,
    chart_code: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    entries = build_field_dictionary()
    if keyword:
        needle = keyword.strip()
        entries = [
            entry for entry in entries
            if needle in entry["字段名"]
            or any(needle in alias for alias in entry["别名"])
            or needle in entry["图表编号"]
            or needle in entry["图表名称"]
            or needle in entry["来源"]
        ]
    if field_type:
        entries = [entry for entry in entries if entry["类型"] == field_type]
    if source:
        entries = [entry for entry in entries if source in entry["来源"]]
    if chart_code:
        entries = [entry for entry in entries if chart_code in entry["图表编号"]]
    total = len(entries)
    start = max(page - 1, 0) * size
    return entries[start:start + size], total


def extract_binding_target(binding: Any) -> dict[str, Any]:
    """从绑定里抽取图表和字段信息。

    看板生成横轴绑定、创建待复核项都调用这一处，保证两处对「绑定属于哪个图表、
    字段是什么」的理解完全一致。
    """
    if isinstance(binding, dict):
        return {
            "字段名": _text(
                binding.get("字段名")
                or binding.get("坐标字段")
                or binding.get("横轴字段")
                or binding.get("字段")
            ),
            "图表编号": _text(
                binding.get("图表编号") or binding.get("图表代码") or binding.get("chart_id")
            ),
            "图表名称": _text(binding.get("图表名称") or binding.get("图表")),
            "来源": _text(binding.get("来源") or binding.get("数据来源")),
        }
    return {
        "字段名": _text(binding),
        "图表编号": "",
        "图表名称": "",
        "来源": "",
    }


def _binding_specs(values: dict[str, Any]) -> list[Any]:
    """取看板的坐标绑定；旧配置可能只写了一个坐标字段。"""
    for key in ("坐标绑定", "横轴绑定", "坐标字段", "横轴字段"):
        value = values.get(key)
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
        return _as_list(value)
    return []


def _chart_scope(dashboard: dict[str, Any]) -> set[str]:
    """看板「包含图表」里声明的图表编号/名称，用来收窄同名候选。"""
    return set(_as_list(dashboard.get("包含图表")))


def _narrow(
    candidates: list[dict[str, Any]],
    target: dict[str, Any],
    scope: set[str],
) -> list[dict[str, Any]]:
    narrowed = candidates
    explicit = False
    if target["图表编号"]:
        narrowed = [entry for entry in narrowed if entry["图表编号"] == target["图表编号"]]
        explicit = True
    if target["图表名称"]:
        narrowed = [entry for entry in narrowed if entry["图表名称"] == target["图表名称"]]
        explicit = True
    if target["来源"]:
        narrowed = [entry for entry in narrowed if entry["来源"] == target["来源"]]
        explicit = True
    if not explicit and scope:
        # 绑定只写了字段名时，用看板包含的图表消歧，避免把其他来源的同名字段合并进来。
        scoped = [
            entry for entry in candidates
            if entry["图表编号"] in scope
            or entry["图表名称"] in scope
            or entry["来源"] in scope
        ]
        if scoped:
            narrowed = scoped
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in narrowed:
        identity = _entry_identity(entry)
        if identity not in seen:
            seen.add(identity)
            unique.append(entry)
    return unique


def _resolve(target: dict[str, Any], scope: set[str]) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    """返回 (命中的字典条目, 同名候选, 未绑定原因)。"""
    candidates = find_field_candidates(target["字段名"])
    if not candidates:
        return None, [], UNBOUND_UNKNOWN
    narrowed = _narrow(candidates, target, scope)
    if not narrowed:
        return None, candidates, UNBOUND_MISMATCH
    if len(narrowed) > 1:
        # 同名候选来自不同来源且无法消歧：不自动合并，留给人工复核。
        return None, narrowed, UNBOUND_COLLISION
    return narrowed[0], candidates, ""


def _review_key(
    dashboard_code: str, target: dict[str, Any], candidates: list[dict[str, Any]],
) -> tuple[Any, ...]:
    return (
        dashboard_code,
        target["字段名"],
        tuple(sorted(_entry_identity(entry) for entry in candidates)),
    )


def reset_runtime_state() -> None:
    """清空确认关系和待复核项，供测试或本地重新演示时使用。"""
    with _BINDING_LOCK:
        _BINDINGS.clear()
        _REVIEWS.clear()


def _build_review(
    dashboard_code: str,
    target: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """名称碰撞生成待复核项的内容；预览和落库共用同一份结构。"""
    if len(candidates) < 2:
        return None
    key = _review_key(dashboard_code, target, candidates)
    with _BINDING_LOCK:
        next_id = max((int(item.get("id", 0)) for item in _REVIEWS), default=0) + 1
    return {
        "id": next_id,
        "看板编号": dashboard_code,
        "字段名": target["字段名"],
        "图表编号": target["图表编号"],
        "图表名称": target["图表名称"],
        "字段类型": sorted({entry["类型"] for entry in candidates}),
        "候选来源": [
            {
                "来源": entry["来源"],
                "图表编号": entry["图表编号"],
                "图表名称": entry["图表名称"],
                "类型": entry["类型"],
            }
            for entry in candidates
        ],
        "原因": "同一字段名在多个来源出现且类型不一致，需人工确认",
        "状态": REVIEW_PENDING,
        "_key": key,
    }


def _register_review(review: dict[str, Any] | None) -> dict[str, Any] | None:
    """把待复核项落库；同一碰撞只保留一条。"""
    if review is None:
        return None
    with _BINDING_LOCK:
        for stored in _REVIEWS:
            if stored["_key"] == review["_key"]:
                return stored
        review["id"] = max((int(item.get("id", 0)) for item in _REVIEWS), default=0) + 1
        _REVIEWS.append(review)
        return review


def _public(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


def _binding_key(dashboard_code: str, entry: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        dashboard_code,
        _text(entry["来源"]),
        _text(entry["图表编号"]),
        _text(entry["字段名"]),
    )


def _persist_binding(
    dashboard_code: str, entry: dict[str, Any], requested_name: str,
) -> tuple[dict[str, Any], bool]:
    """写入一条确认关系；同一来源的同一字段已经确认过时直接复用。"""
    key = _binding_key(dashboard_code, entry)
    with _BINDING_LOCK:
        rows = _BINDINGS.setdefault(dashboard_code, [])
        for row in rows:
            if row["_key"] == key:
                return row, False
        row = {
            "id": max((int(item.get("id", 0)) for item in rows), default=0) + 1,
            "看板编号": dashboard_code,
            "图表编号": entry["图表编号"],
            "图表名称": entry["图表名称"],
            "来源": entry["来源"],
            "横轴": requested_name,
            "字段名": entry["字段名"],
            "类型": entry["类型"],
            "可聚合": entry["可聚合"],
            "可求和": entry["可求和"],
            "可运算": entry["可运算"],
            "状态": "已确认",
            "_key": key,
        }
        rows.append(row)
        return row, True


def _slim_binding(entry: dict[str, Any], requested_name: str) -> dict[str, Any]:
    return {
        "看板编号": entry["看板编号"],
        "图表编号": entry["图表编号"],
        "图表名称": entry["图表名称"],
        "来源": entry["来源"],
        "横轴": requested_name,
        "字段名": entry["字段名"],
        "类型": entry["类型"],
        "可聚合": entry["可聚合"],
        "可求和": entry["可求和"],
        "可运算": entry["可运算"],
        "状态": entry["状态"],
    }


def _confirmed(dashboard_code: str) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    return {row["_key"]: row for row in _BINDINGS.get(dashboard_code, [])}


def generate_axis_bindings(
    dashboard: dict[str, Any],
    *,
    specs: list[Any] | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    """按图表消费字段字典给看板生成可运算的横轴绑定。

    - 同一看板的同一来源字段重复提交只保留一条确认关系；
    - 来源不同的同名字段各成一条，不自动合并；
    - 解析不了的字段进入未绑定项，名称碰撞额外形成待复核项。
    """
    dashboard_code = _text(dashboard.get("看板编号")) or str(int(dashboard.get("id", 0)))
    scope = _chart_scope(dashboard)
    requested = specs if specs is not None else _binding_specs(dashboard)

    items: list[dict[str, Any]] = []
    unbound: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    confirmed = _confirmed(dashboard_code)
    created_count = 0

    for spec in requested:
        target = extract_binding_target(spec)
        if not target["字段名"]:
            continue
        entry, candidates, reason = _resolve(target, scope)
        if entry is None:
            unbound.append({
                "横轴": target["字段名"],
                "图表编号": target["图表编号"],
                "图表名称": target["图表名称"],
                "来源": target["来源"],
                "未绑定原因": reason,
            })
            # 名称碰撞才形成待复核项；名称不明只是未绑定，不占用复核队列。
            if reason == UNBOUND_COLLISION:
                review = _build_review(dashboard_code, target, candidates)
                if persist:
                    review = _register_review(review)
                if review is not None and all(item["_key"] != review["_key"] for item in reviews):
                    reviews.append(review)
            continue

        key = _binding_key(dashboard_code, entry)
        if key in seen:
            continue
        seen.add(key)
        if persist:
            row, created = _persist_binding(dashboard_code, entry, target["字段名"])
            created_count += 1 if created else 0
        else:
            row = {
                "看板编号": dashboard_code,
                "图表编号": entry["图表编号"],
                "图表名称": entry["图表名称"],
                "来源": entry["来源"],
                "字段名": entry["字段名"],
                "类型": entry["类型"],
                "可聚合": entry["可聚合"],
                "可求和": entry["可求和"],
                "可运算": entry["可运算"],
                "状态": "已确认" if key in confirmed else "待确认",
            }
        items.append(_slim_binding(row, target["字段名"]))

        # 即使按看板包含的图表消除了歧义，显示名跨来源碰撞仍要留下待复核项。
        if len(candidates) > 1:
            review = _build_review(dashboard_code, target, candidates)
            if persist:
                review = _register_review(review)
            if review is not None and all(item["_key"] != review["_key"] for item in reviews):
                reviews.append(review)

    if persist:
        # 已落库但本次没有重新提交的待复核项也要带出来。
        for review in _REVIEWS:
            if review["看板编号"] == dashboard_code and review["状态"] == REVIEW_PENDING:
                if all(item["_key"] != review["_key"] for item in reviews):
                    reviews.append(review)

    return {
        "看板编号": dashboard_code,
        "total": len(items),
        "items": [_public(item) for item in items],
        "未绑定项": unbound,
        "待复核项": [_public(review) for review in reviews],
        "新增确认": created_count,
    }


def confirm_axis_bindings(
    dashboard: dict[str, Any], values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """提交坐标绑定并落库；values 里带了新绑定就写回看板记录。"""
    specs: list[Any] | None = None
    if values:
        for key in ("坐标绑定", "横轴绑定", "坐标字段", "横轴字段"):
            if values.get(key) not in (None, "", []):
                specs = _binding_specs({key: values.get(key)})
                dashboard[key] = values.get(key)
                break
    return generate_axis_bindings(dashboard, specs=specs, persist=True)


def stored_bindings(dashboard_code: str) -> list[dict[str, Any]]:
    return [
        _slim_binding(row, _text(row.get("横轴")))
        for row in _BINDINGS.get(dashboard_code, [])
    ]


def review_items(dashboard_code: str | None = None) -> list[dict[str, Any]]:
    return [
        _public(review)
        for review in _REVIEWS
        if dashboard_code is None or review["看板编号"] == dashboard_code
    ]
