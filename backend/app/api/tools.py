"""应急工具箱 API 路由.

提供 10 个 REST 端点：
  GET    /api/tools             — 工具列表（搜索/分类/分页）
  GET    /api/tools/stats       — 统计概览
  GET    /api/tools/categories  — 分类列表（含计数）
  POST   /api/tools             — 上传新工具（admin only）
  GET    /api/tools/{tool_id}   — 工具详情（含版本历史）
  PUT    /api/tools/{tool_id}   — 更新工具信息
  DELETE /api/tools/{tool_id}   — 删除工具
  POST   /api/tools/{tool_id}/versions — 发布新版本
  GET    /api/tools/{tool_id}/download — 下载工具文件
  GET    /api/tools/{tool_id}/doc      — 查看/下载操作文档
"""
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.models.tool import Tool, ToolVersion
from app.services.auth_service import get_current_user
from app.services.tool_service import (
    create_tool,
    delete_tool,
    download_tool,
    get_doc,
    publish_version,
    update_tool,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tools", tags=["应急工具箱"])


@router.get("")
def list_tools(
    keyword: str = Query(default="", max_length=100),
    category: str = Query(default=""),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="DESC"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """工具列表（搜索/分类/分页）.

    Query 参数:
        keyword: 名称/描述模糊搜索.
        category: 分类筛选（"全部"表示不过滤）.
        sort_by: 排序字段 updated_at / created_at / download_count / name.
        sort_dir: ASC 或 DESC.
        offset: 分页偏移.
        limit: 每页数量（上限 200）.

    Returns:
        {code: 0, data: {items: [...], total: int}, message: "success"}.
    """
    tools = Tool.search(
        keyword=keyword,
        category=category,
        sort_by=sort_by,
        sort_dir=sort_dir,
        offset=offset,
        limit=limit,
    )
    total = Tool.count(keyword=keyword, category=category)
    return {"code": 0, "data": {"items": tools, "total": total}, "message": "success"}


@router.get("/stats")
def get_stats(current_user: dict = Depends(get_current_user)):
    """统计概览.

    Returns:
        {code: 0, data: {total, downloads, today, categories}, message: "success"}.
    """
    stats = Tool.get_stats()
    return {"code": 0, "data": stats, "message": "success"}


@router.get("/categories")
def get_categories(current_user: dict = Depends(get_current_user)):
    """分类列表（含各分类计数）.

    Returns:
        {code: 0, data: [{category, count}, ...], message: "success"}.
    """
    cats = Tool.get_categories()
    return {"code": 0, "data": cats, "message": "success"}


@router.post("")
async def upload_tool(
    name: str = Form(...),
    description: str = Form(default=""),
    category: str = Form(default="other"),
    version: str = Form(default="1.0.0"),
    tags: str = Form(default="[]"),
    tool_file: UploadFile = File(...),
    doc_file: UploadFile | None = File(default=None),
    current_user: dict = Depends(get_current_user),
):
    """上传新工具（仅 admin 角色）.

    请求体为 multipart/form-data:
        name: 工具名称（必填）.
        description: 简要描述.
        category: 分类.
        version: 版本号（默认 1.0.0，需符合 semver）.
        tags: JSON 字符串数组.
        tool_file: 工具文件（必填，最大 200MB）.
        doc_file: 操作文档（可选，最大 50MB）.

    Returns:
        {code: 0, data: tool_object, message: "上传成功"}.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可上传工具")
    try:
        tags_list = json.loads(tags)
    except (json.JSONDecodeError, TypeError):
        tags_list = []
    result = await create_tool(
        name=name,
        description=description,
        category=category,
        version=version,
        tags=tags_list,
        author_id=current_user["id"],
        tool_file=tool_file,
        doc_file=doc_file,
    )
    return {"code": 0, "data": result, "message": "上传成功"}


@router.get("/{tool_id}")
def get_tool(tool_id: int, current_user: dict = Depends(get_current_user)):
    """工具详情（含版本历史）.

    Returns:
        {code: 0, data: tool_with_versions, message: "success"}.
    """
    tool = Tool.get_by_id(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    versions = ToolVersion.get_by_tool_id(tool_id)
    tool["versions"] = versions
    return {"code": 0, "data": tool, "message": "success"}


@router.put("/{tool_id}")
async def update_tool_api(
    tool_id: int,
    name: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    category: Optional[str] = Form(default=None),
    tags: Optional[str] = Form(default=None),
    current_user: dict = Depends(get_current_user),
):
    """更新工具基本信息.

    仅更新非空字段，不涉及文件变更。

    Returns:
        {code: 0, data: updated_tool, message: "更新成功"}.
    """
    data = {}
    if name is not None:
        data["name"] = name
    if description is not None:
        data["description"] = description
    if category is not None:
        data["category"] = category
    if tags is not None:
        try:
            data["tags"] = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            data["tags"] = []
    result = await update_tool(tool_id, data, current_user)
    return {"code": 0, "data": result, "message": "更新成功"}


@router.delete("/{tool_id}")
async def delete_tool_api(
    tool_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除工具（admin 或上传者本人）.

    物理删除：清理磁盘文件 + 数据库记录（ON DELETE CASCADE）。

    Returns:
        {code: 0, data: None, message: "已删除"}.
    """
    await delete_tool(tool_id, current_user)
    return {"code": 0, "data": None, "message": "已删除"}


@router.post("/{tool_id}/versions")
async def publish_version_api(
    tool_id: int,
    version: str = Form(...),
    change_log: str = Form(default=""),
    tool_file: UploadFile = File(...),
    doc_file: UploadFile | None = File(default=None),
    current_user: dict = Depends(get_current_user),
):
    """发布新版本（admin 或作者本人）.

    请求体为 multipart/form-data:
        version: 版本号（必填，semver 格式）.
        change_log: 更新日志.
        tool_file: 工具文件（必填）.
        doc_file: 操作文档（可选）.

    Returns:
        {code: 0, data: tool_object, message: "版本发布成功"}.
    """
    result = await publish_version(
        tool_id=tool_id,
        version=version,
        change_log=change_log,
        tool_file=tool_file,
        doc_file=doc_file,
        current_user=current_user,
    )
    return {"code": 0, "data": result, "message": "版本发布成功"}


@router.get("/{tool_id}/download")
async def download_tool_api(
    tool_id: int,
    current_user: dict = Depends(get_current_user),
):
    """下载工具文件.

    返回文件流（StreamingResponse），自动触发下载计数。

    Returns:
        FileResponse: 文件流 + Content-Disposition header.
    """
    file_path, file_name = await download_tool(tool_id, current_user)
    return FileResponse(
        path=file_path,
        filename=file_name,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/{tool_id}/doc")
async def view_doc_api(
    tool_id: int,
    current_user: dict = Depends(get_current_user),
):
    """查看操作文档内容.

    根据文档类型返回：
        - .md / .html 返回文本内容，由前端渲染.
        - .pdf 返回文件流供浏览器内嵌预览.

    Returns:
        dict | FileResponse: 文本内容或 PDF 文件流.
    """
    result = await get_doc(tool_id)
    file_type = result.get("file_type", "")

    if file_type == "pdf":
        file_path = result.get("file_path", "")
        file_name = result.get("file_name", "document.pdf")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文档文件不存在")
        return FileResponse(
            path=file_path,
            filename=file_name,
            media_type="application/pdf",
        )

    return {"code": 0, "data": result, "message": "success"}
