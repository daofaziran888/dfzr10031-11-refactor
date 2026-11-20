"""数据看板业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.field_specs import DASHBOARD_COLUMNS
from app.store import store

MODULE = "dashboard"
REQUIRED_FIELDS = ["看板编号", "看板名称", "包含图表"]
# 可选字段只在调用方提交时保存，历史看板的旧键（例如已更正的坐标字段名）保持原样。
OPTIONAL_FIELDS = list(DASHBOARD_COLUMNS)
STATUS_ORDER = ["待配置", "已发布", "展示中", "已下线"]
ACTION_RULES = {"完成配置": "已发布", "发布看板": "展示中", "下线看板": "已下线"}
NEGATIVE_ACTIONS = ["下线看板"]


class DashboardService:
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
            rows = [row for row in rows if keyword in str(row.get("看板编号", ""))]
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
        for field in OPTIONAL_FIELDS:
            if field in REQUIRED_FIELDS:
                continue
            if values.get(field) is not None:
                entry[field] = values.get(field)
        # 坐标绑定是看板自身状态，原样保留调用方写法（包括更正前的旧字段名）。
        for field in ("坐标绑定", "横轴绑定", "坐标字段", "横轴字段"):
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
            return None, f"看板配置 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据看板可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"看板配置已{action}"
