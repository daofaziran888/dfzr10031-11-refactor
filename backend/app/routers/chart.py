"""图表配置接口：维护图表，覆盖保存配置、发布图表、停用图表等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.field_specs import CHART_COLUMNS
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.chart import ChartService
from app.services.chart_fields import (
    list_field_dictionary,
    review_items,
)

router = APIRouter(prefix="/api/chart", tags=["图表配置"])

service = ChartService()

# 列字段说明统一维护在 app/field_specs.py，列表、导出和字段字典共用同一份顺序。
LIST_FIELDS = list(CHART_COLUMNS)
STATUSES = ["草稿", "已配置", "已发布", "已停用"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出图表配置清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "chart", "total": total, "items": items}


@router.get("/fields")
def list_fields(
    keyword: str | None = Query(default=None, description="按字段名、别名、图表编号或来源检索"),
    field_type: str | None = Query(default=None, description="数值、字符"),
    source: str | None = Query(default=None, description="按数据来源过滤"),
    chart_code: str | None = Query(default=None, description="按图表编号过滤"),
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """图表消费字段字典：给出每个字段的来源、类型和别名，供列表、导出和看板共用。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = list_field_dictionary(
        keyword=keyword,
        field_type=field_type,
        source=source,
        chart_code=chart_code,
        page=page,
        size=size,
    )
    return {"module": "chart.fields", "total": total, "page": page, "size": size, "items": items}


@router.get("/fields/export")
def export_fields(
    keyword: str | None = Query(default=None),
    field_type: str | None = Query(default=None),
    source: str | None = Query(default=None),
    chart_code: str | None = Query(default=None),
) -> dict[str, Any]:
    """导出字段字典全量数据，字段名、顺序与列表接口一致。"""
    items, total = list_field_dictionary(
        keyword=keyword,
        field_type=field_type,
        source=source,
        chart_code=chart_code,
        page=1,
        size=10000,
    )
    return {"module": "chart.fields", "total": total, "items": items}


@router.get("/fields/reviews")
def list_field_reviews(
    dashboard_code: str | None = Query(default=None, description="按看板编号过滤待复核项"),
) -> dict[str, Any]:
    """名称碰撞形成的待复核项；两处（生成绑定与复核列表）共用同一套字段抽取。"""
    items = review_items(dashboard_code)
    return {"module": "chart.fields.reviews", "total": len(items), "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按图表编号检索"),
    status: str | None = Query(default=None, description="草稿、已配置、已发布、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按图表编号与状态过滤图表配置列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条图表明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"图表 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条图表，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="图表已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条图表执行保存配置、发布图表、停用图表；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
