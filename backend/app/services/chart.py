"""图表配置业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.field_specs import CHART_COLUMNS, CHART_FIELD_METADATA_FIELDS, CHART_OPTIONAL_FIELDS
from app.store import store

MODULE = "chart"
REQUIRED_FIELDS = ["图表编号", "图表名称", "图表类型"]
# 可选字段只在调用方提交时保存，旧调用方不提交就不会出现在输出里。
OPTIONAL_FIELDS = list(dict.fromkeys(
    CHART_OPTIONAL_FIELDS + CHART_FIELD_METADATA_FIELDS + CHART_COLUMNS
))
STATUS_ORDER = ["草稿", "已配置", "已发布", "已停用"]
ACTION_RULES = {"保存配置": "已配置", "发布图表": "已发布", "停用图表": "已停用"}
NEGATIVE_ACTIONS = ["停用图表"]


class ChartService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        extra: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("图表编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if extra:
            for field, val in extra.items():
                rows = [row for row in rows if val in str(row.get(field, ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 字段元数据（数据来源、坐标字段、字段列表/类型/别名等）随登记一起收下，
        # 供图表消费字段字典区分同名不同来源的字段。
        for field in OPTIONAL_FIELDS:
            if field in REQUIRED_FIELDS:
                continue
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"图表 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于图表配置可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"图表已{action}"
