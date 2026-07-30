"""应急工具业务逻辑层."""
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.models.tool import Tool, ToolDownload, ToolVersion

logger = logging.getLogger(__name__)

# 文件存储根目录
TOOLS_STORAGE = Path(__file__).resolve().parent.parent / "data" / "tools"

# 版本号正则（semver）
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# 允许的工具文件扩展名
ALLOWED_EXTENSIONS = {
    ".exe", ".zip", ".tar.gz", ".gz", ".py", ".ps1",
    ".sh", ".bat", ".bin", ".msi", ".dmg", ".app",
}

# 允许的文档文件扩展名
ALLOWED_DOC_EXTENSIONS = {".md", ".pdf", ".html", ".htm"}

# 最大文件大小：200MB
MAX_TOOL_FILE_SIZE = 200 * 1024 * 1024
# 最大文档大小：50MB
MAX_DOC_FILE_SIZE = 50 * 1024 * 1024


def _ensure_dir(path: Path) -> None:
    """确保目录存在，自动创建."""
    path.mkdir(parents=True, exist_ok=True)


def _get_ext(filename: str) -> str:
    """安全获取文件扩展名（含多级后缀如 .tar.gz）. """
    name = Path(filename).name
    # 处理 .tar.gz 等双后缀
    if name.endswith(".tar.gz"):
        return ".tar.gz"
    # 处理 .tar.bz2 等
    if name.endswith(".tar.bz2"):
        return ".tar.bz2"
    ext = Path(name).suffix
    return ext if ext else ".bin"


def _save_file(upload: UploadFile, target_dir: Path) -> tuple[str, str, int, str]:
    """保存上传文件，返回 (file_name, file_path, file_size, file_hash).

    Raises:
        HTTPException: 文件大小超限或读取错误时.
    """
    ext = _get_ext(upload.filename or "file")
    unique_name = f"{uuid.uuid4().hex}{ext}"
    target_path = target_dir / unique_name
    _ensure_dir(target_dir)
    content = upload.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件内容为空")
    file_hash = hashlib.sha256(content).hexdigest()
    with open(target_path, "wb") as f:
        f.write(content)
    return upload.filename or "file", str(target_path), len(content), file_hash


def _delete_file(file_path: str) -> None:
    """安全删除文件（忽略不存在错误），并递归清理空目录."""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            # 递归清理空父目录
            parent = os.path.dirname(file_path)
            while parent and parent.startswith(str(TOOLS_STORAGE)):
                if os.path.isdir(parent) and not os.listdir(parent):
                    os.rmdir(parent)
                    parent = os.path.dirname(parent)
                else:
                    break
    except Exception as e:
        logger.warning("Failed to delete file %s: %s", file_path, e)


async def create_tool(
    name: str,
    description: str,
    category: str,
    version: str,
    tags: list,
    author_id: int,
    tool_file: UploadFile,
    doc_file: UploadFile | None,
) -> dict:
    """上传新工具.

    Args:
        name: 工具名称.
        description: 简要描述.
        category: 分类.
        version: semver 版本号.
        tags: 标签列表.
        author_id: 上传用户 ID.
        tool_file: 工具文件.
        doc_file: 操作文档（可选）.

    Returns:
        dict: 完整 tool 对象.

    Raises:
        HTTPException: 参数校验失败或文件处理错误.
    """
    # 校验版本号
    if not VERSION_RE.match(version):
        raise HTTPException(status_code=400, detail="版本号格式无效，请使用 x.y.z 格式")

    # 校验文件大小
    tool_file.file.seek(0, os.SEEK_END)
    tool_size = tool_file.file.tell()
    tool_file.file.seek(0)
    if tool_size > MAX_TOOL_FILE_SIZE:
        raise HTTPException(status_code=400, detail="工具文件超过 200MB 限制")

    # 先插入数据库获取 tool_id
    tool_id = Tool.create(
        name=name,
        description=description,
        category=category,
        author_id=author_id,
        version=version,
        tags=tags,
        file_name="",
        file_path="",
        file_size=0,
        file_hash="",
    )

    # 创建文件存储目录
    version_dir = TOOLS_STORAGE / str(tool_id)
    _ensure_dir(version_dir)

    # 保存工具文件
    fname, fpath, fsize, fhash = _save_file(tool_file, version_dir)
    doc_name, doc_path, doc_type = "", "", ""
    if doc_file:
        doc_file.file.seek(0, os.SEEK_END)
        doc_size = doc_file.file.tell()
        doc_file.file.seek(0)
        if doc_size > MAX_DOC_FILE_SIZE:
            raise HTTPException(status_code=400, detail="文档文件超过 50MB 限制")
        dname, dpath, _, _ = _save_file(doc_file, version_dir)
        doc_name, doc_path = dname, dpath
        doc_type = _get_ext(doc_name)

    # 更新版本记录的文件信息
    from app.database import get_connection

    with get_connection() as conn:
        conn.execute(
            """UPDATE tool_versions SET file_name=?, file_path=?, file_size=?,
               file_hash=?, doc_file_name=?, doc_file_path=?, doc_file_type=?
               WHERE tool_id=?""",
            (fname, fpath, fsize, fhash, doc_name, doc_path, doc_type, tool_id),
        )

    return Tool.get_by_id(tool_id) or {}


async def update_tool(tool_id: int, data: dict, current_user: dict) -> dict:
    """更新工具信息.

    Raises:
        HTTPException: 工具不存在或权限不足.
    """
    tool = Tool.get_by_id(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    if current_user.get("role") != "admin" and tool.get("author_id") != current_user.get("id"):
        raise HTTPException(status_code=403, detail="无权修改此工具")

    Tool.update(tool_id, **data)
    return Tool.get_by_id(tool_id) or {}


async def delete_tool(tool_id: int, current_user: dict) -> None:
    """删除工具（清理文件 + 数据库）.

    Raises:
        HTTPException: 工具不存在或权限不足.
    """
    tool = Tool.get_by_id(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    if current_user.get("role") != "admin" and tool.get("author_id") != current_user.get("id"):
        raise HTTPException(status_code=403, detail="无权删除此工具")

    # 清理磁盘文件
    tool_dir = TOOLS_STORAGE / str(tool_id)
    if tool_dir.exists():
        shutil.rmtree(tool_dir, ignore_errors=True)

    # 删除数据库记录（ON DELETE CASCADE 自动清理关联表）
    Tool.delete(tool_id)


async def publish_version(
    tool_id: int,
    version: str,
    change_log: str,
    tool_file: UploadFile,
    doc_file: UploadFile | None,
    current_user: dict,
) -> dict:
    """为已有工具发布新版本.

    Raises:
        HTTPException: 参数校验失败、工具不存在、权限不足或版本重复.
    """
    tool = Tool.get_by_id(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    if current_user.get("role") != "admin" and tool.get("author_id") != current_user.get("id"):
        raise HTTPException(status_code=403, detail="无权操作")
    if not VERSION_RE.match(version):
        raise HTTPException(status_code=400, detail="版本号格式无效，请使用 x.y.z 格式")

    # 校验版本号不重复
    existing_versions = ToolVersion.get_by_tool_id(tool_id)
    if any(v["version"] == version for v in existing_versions):
        raise HTTPException(status_code=409, detail=f"版本号 {version} 已存在")

    # 校验文件大小
    tool_file.file.seek(0, os.SEEK_END)
    tool_size = tool_file.file.tell()
    tool_file.file.seek(0)
    if tool_size > MAX_TOOL_FILE_SIZE:
        raise HTTPException(status_code=400, detail="工具文件超过 200MB 限制")

    version_dir = TOOLS_STORAGE / str(tool_id)
    fname, fpath, fsize, fhash = _save_file(tool_file, version_dir)
    doc_name, doc_path, doc_type = "", "", ""
    if doc_file:
        doc_file.file.seek(0, os.SEEK_END)
        doc_size = doc_file.file.tell()
        doc_file.file.seek(0)
        if doc_size > MAX_DOC_FILE_SIZE:
            raise HTTPException(status_code=400, detail="文档文件超过 50MB 限制")
        dname, dpath, _, _ = _save_file(doc_file, version_dir)
        doc_name, doc_path = dname, dpath
        doc_type = _get_ext(doc_name)

    ToolVersion.create(
        tool_id=tool_id,
        version=version,
        file_name=fname,
        file_path=fpath,
        file_size=fsize,
        file_hash=fhash,
        doc_file_name=doc_name,
        doc_file_path=doc_path,
        doc_file_type=doc_type,
        change_log=change_log,
    )
    return Tool.get_by_id(tool_id) or {}


async def download_tool(tool_id: int, current_user: dict) -> tuple[str, str]:
    """获取工具下载信息，返回 (file_path, file_name).

    Raises:
        HTTPException: 工具不存在或无可用版本.
    """
    tool = Tool.get_by_id(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")

    versions = ToolVersion.get_by_tool_id(tool_id)
    if not versions:
        raise HTTPException(status_code=404, detail="无可用版本")
    latest = versions[0]

    file_path = latest["file_path"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="工具文件不存在")

    # 记录下载
    ToolDownload.log(
        tool_id=tool_id,
        version_id=latest["id"],
        user_id=current_user.get("id"),
        ip_address="",
    )
    return file_path, latest["file_name"]


async def get_doc(tool_id: int) -> dict:
    """获取操作文档内容.

    Returns:
        dict: {content: str, file_type: str, file_name: str}.

    Raises:
        HTTPException: 工具不存在或无文档.
    """
    tool = Tool.get_by_id(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")

    versions = ToolVersion.get_by_tool_id(tool_id)
    if not versions or not versions[0].get("doc_file_path"):
        raise HTTPException(status_code=404, detail="无操作文档")

    latest = versions[0]
    doc_path = latest["doc_file_path"]
    doc_type = latest.get("doc_file_type", "")

    if not os.path.exists(doc_path):
        raise HTTPException(status_code=404, detail="文档文件不存在")

    # .pdf 类型暂不返回内容，前端通过单独 URL 访问文件流
    if doc_type == "pdf":
        return {
            "content": "",
            "file_type": "pdf",
            "file_name": latest.get("doc_file_name", "document.pdf"),
            "file_path": doc_path,
        }

    # .md / .html / .txt 等文本类型读取内容
    try:
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(doc_path, "r", encoding="latin-1") as f:
            content = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文档失败: {e}") from e

    return {
        "content": content,
        "file_type": doc_type or "md",
        "file_name": latest.get("doc_file_name", "document.md"),
    }
