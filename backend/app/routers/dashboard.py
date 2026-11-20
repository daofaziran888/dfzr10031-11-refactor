"""数据看板接口：维护看板配置，覆盖完成配置、发布看板、下线看板等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.field_specs import DASHBOARD_COLUMNS
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.chart_fields import (
    confirm_axis_bindings,
    generate_axis_bindings,
    stored_bindings,
)
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["数据看板"])

service = DashboardService()

# 列字段说明统一维护在 app/field_specs.py，列表、导出和字段字典共用同一份顺序。
LIST_FIELDS = list(DASHBOARD_COLUMNS)
STATUSES = ["待配置", "已发布", "展示中", "已下线"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出数据看板清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "dashboard", "total": total, "items": items}


@router.get("/{entry_id}/axis-bindings")
def axis_bindings(entry_id: int) -> dict[str, Any]:
    """按图表消费字段字典预览看板的横轴绑定，不改动看板状态。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"看板配置 {entry_id} 不存在或已归档")
    return generate_axis_bindings(entry)


@router.post("/{entry_id}/axis-bindings", response_model=ActionResult)
def confirm_bindings(entry_id: int, payload: EntryPayload) -> ActionResult:
    """提交坐标绑定；同一看板同一来源字段重复提交只记一次确认关系。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=f"看板配置 {entry_id} 不存在或已归档")
    result = confirm_axis_bindings(entry, payload.values)
    created = int(result.get("新增确认", 0))
    unbound = len(result.get("未绑定项") or [])
    message = f"坐标绑定已确认 {created} 条"
    if unbound:
        message += f"，{unbound} 条未绑定"
    return ActionResult(ok=True, message=message, entry=result)


@router.get("/{entry_id}/axis-bindings/confirmed")
def list_confirmed_bindings(entry_id: int) -> dict[str, Any]:
    """读取看板已落库的确认关系，供排查重复提交与同名字段。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"看板配置 {entry_id} 不存在或已归档")
    dashboard_code = str(entry.get("看板编号") or entry.get("id"))
    items = stored_bindings(dashboard_code)
    return {"看板编号": dashboard_code, "total": len(items), "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按看板编号检索"),
    status: str | None = Query(default=None, description="待配置、已发布、展示中、已下线"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按看板编号与状态过滤数据看板列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条看板配置明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"看板配置 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条看板配置，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="看板配置已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条看板配置执行完成配置、发布看板、下线看板；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
