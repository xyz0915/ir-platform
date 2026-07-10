"""报告模板配置读写服务（任务⑤ 分级报告）.

配置位于 ``backend/config/report_template.json``，结构见增量设计 §3.6：
    {
      "logo_path": "",
      "header_text": "XX 公司 安全应急响应报告",
      "footer_text": "CONFIDENTIAL — 仅限内部",
      "sections": ["summary","risk","timeline","findings","checklist"],
      "executive": {"masked": true, "chart_only": true, "include_checklist": false},
      "technical": {"masked": false, "chart_only": false, "include_checklist": true}
    }
"""

import json
import logging
import os
from typing import Any, Dict

from app.config import settings

logger = logging.getLogger(__name__)


class ReportTemplateService:
    """报告模板配置读写（单例配置，落盘 JSON）."""

    DEFAULT_TEMPLATE: Dict[str, Any] = {
        "logo_path": "",
        "header_text": "个人应急响应平台 安全分析报告",
        "footer_text": "CONFIDENTIAL — 仅限内部使用",
        "sections": ["summary", "risk", "timeline", "findings", "checklist"],
        "executive": {
            "masked": True,
            "chart_only": True,
            "include_checklist": False,
        },
        "technical": {
            "masked": False,
            "chart_only": False,
            "include_checklist": True,
        },
    }

    @staticmethod
    def _path() -> str:
        return str(settings.REPORT_TEMPLATE_PATH)

    @classmethod
    def get_template(cls) -> Dict[str, Any]:
        """读取报告模板配置；缺文件或异常时返回默认配置."""
        path = cls._path()
        if not os.path.exists(path):
            return dict(cls.DEFAULT_TEMPLATE)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return dict(cls.DEFAULT_TEMPLATE)
            # 合并默认值，确保字段完整
            merged = dict(cls.DEFAULT_TEMPLATE)
            merged.update(data)
            for key in ("executive", "technical"):
                if isinstance(data.get(key), dict):
                    merged[key] = {**cls.DEFAULT_TEMPLATE[key], **data[key]}
            return merged
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("读取报告模板配置失败，回退默认: %s", exc)
            return dict(cls.DEFAULT_TEMPLATE)

    @classmethod
    def update_template(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """更新报告模板配置（浅合并顶层字段 + executive/technical 子字典）并落盘."""
        merged = cls.get_template()
        for k, v in (values or {}).items():
            if k in ("executive", "technical") and isinstance(v, dict):
                merged[k] = {**merged.get(k, {}), **v}
            else:
                merged[k] = v

        path = cls._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
        logger.info("报告模板配置已更新")
        return merged
