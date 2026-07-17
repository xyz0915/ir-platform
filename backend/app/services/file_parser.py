"""文件解析服务 — .evtx / .csv / .txt / 图片 → 结构化文本."""
import logging
import os

logger = logging.getLogger(__name__)

class FileParser:
    """文件解析器 — 根据扩展名自动识别格式并提取文本."""

    SUPPORTED_EXTENSIONS = {".evtx", ".csv", ".txt", ".log", ".json", ".png", ".jpg", ".jpeg"}

    @staticmethod
    def parse(filename: str, content_base64: str) -> dict:
        """解析上传文件，返回结构化结果."""
        import base64
        ext = os.path.splitext(filename)[1].lower()
        try:
            raw = base64.b64decode(content_base64)
        except Exception as e:
            return {"success": False, "file_type": ext, "parsed_text": "", "intent": "", "error": f"Base64 decode failed: {e}"}

        if ext == ".evtx":
            return FileParser._parse_evtx(raw, filename)
        elif ext == ".csv":
            return FileParser._parse_csv(raw)
        elif ext in (".txt", ".log"):
            return FileParser._parse_text(raw)
        elif ext == ".json":
            return FileParser._parse_json(raw)
        elif ext in (".png", ".jpg", ".jpeg"):
            return {"success": True, "file_type": ext, "parsed_text": f"[图片] {filename} (无法自动解析图像内容)", "intent": "", "error": ""}
        else:
            return {"success": False, "file_type": ext, "parsed_text": "", "intent": "", "error": f"Unsupported file type: {ext}"}

    @staticmethod
    def _parse_text(raw: bytes) -> dict:
        text = raw.decode("utf-8", errors="replace")[:10000]
        intent = "logs" if any(kw in text for kw in ("log", "日志", "event")) else "text"
        return {"success": True, "file_type": ".txt", "parsed_text": text, "intent": intent, "error": ""}

    @staticmethod
    def _parse_csv(raw: bytes) -> dict:
        text = raw.decode("utf-8", errors="replace")[:5000]
        return {"success": True, "file_type": ".csv", "parsed_text": text, "intent": "logs", "error": ""}

    @staticmethod
    def _parse_json(raw: bytes) -> dict:
        text = raw.decode("utf-8", errors="replace")[:5000]
        return {"success": True, "file_type": ".json", "parsed_text": text, "intent": "alerts", "error": ""}

    @staticmethod
    def _parse_evtx(raw: bytes, filename: str) -> dict:
        text = raw.decode("utf-8", errors="replace")[:5000]
        return {"success": True, "file_type": ".evtx", "parsed_text": text, "intent": "logs", "error": ""}
