"""多源威胁情报 provider 注册中心（任务④）.

各 provider 子类继承 ``BaseThreatIntelProvider`` 实现 ``query()``，
在此集中注册进 ``_PROVIDER_REGISTRY``（key 为 provider type）。

``enrichment_service`` 在模块加载末尾通过 ``register_providers`` 触发注册，
保证 ``create_provider({"type": "virustotal", ...})`` 可返回实例。
"""

from app.services.enrichment_service import _PROVIDER_REGISTRY
from app.services.providers.abuseipdb_provider import AbuseIPDBProvider
from app.services.providers.alienvault_otx_provider import AlienVaultOTXProvider
from app.services.providers.virustotal_provider import VirusTotalProvider

# 注册新增三源（setdefault 保证幂等，不覆盖既有 threatbook）
def register_providers(registry: dict) -> None:
    """将三源 provider 子类注册进共享注册表（幂等）."""
    registry.setdefault("virustotal", VirusTotalProvider)
    registry.setdefault("abuseipdb", AbuseIPDBProvider)
    registry.setdefault("alienvault_otx", AlienVaultOTXProvider)


# 模块导入即注册（enrichment_service 末尾 import 本包时会执行）
register_providers(_PROVIDER_REGISTRY)


__all__ = [
    "VirusTotalProvider",
    "AbuseIPDBProvider",
    "AlienVaultOTXProvider",
    "register_providers",
]
