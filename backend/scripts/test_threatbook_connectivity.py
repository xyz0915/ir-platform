"""微步 ThreatBook 连通性 + 归一化验证脚本（不依赖数据库，可独立运行）。

用途:
  - 验证微步 API key 是否有效、接口是否可达。
  - 验证我们代码的归一化（judgments 优先 / risk_score 兜底 → threat_level）是否正确。

用法:
  # 默认测试 8.8.8.8 与 example.com
  backend\\venv\\Scripts\\python.exe scripts\\test_threatbook_connectivity.py

  # 指定自定义指标（脚本自动按格式判别 ip / domain）
  backend\\venv\\Scripts\\python.exe scripts\\test_threatbook_connectivity.py 1.2.3.4 evil.example.com

  # 顺便验证落库（需初始化数据库，会写入 threat_intel 表）
  backend\\venv\\Scripts\\python.exe scripts\\test_threatbook_connectivity.py --persist 8.8.8.8

前置:
  - 真实微步 key 通过环境变量 THREATBOOK_KEY 注入（与 providers.json 中
    api_key_ref="$THREATBOOK_KEY" 对应）。
  - 本脚本只做真实网络查询，不 mock；缺网络/缺 key 会给出明确错误与退出码。
"""
import argparse
import json
import os
import sys
from pathlib import Path

# 让 `import app` 可用（脚本位于 backend/scripts/ 下）
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# 即使不在带 THREATBOOK_KEY 的终端里运行，也从 backend/.env 兜底加载（override=False）。
from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")  # backend/.env

from app.services.enrichment_service import (  # noqa: E402
    create_provider,
    ThreatIntelQueryError,
    UnsupportedIocTypeError,
    QuotaExceededError,
)

PROVIDERS_JSON = BACKEND_ROOT / "scripts" / "threat_intel_providers.json"

DEFAULT_SAMPLES = [
    ("ip", "8.8.8.8"),
    ("domain", "example.com"),
]


def _guess_type(value: str) -> str:
    """极简判别：四段纯数字且恰 3 个点 → ip，其余 → domain。"""
    if value.replace(".", "").isdigit() and value.count(".") == 3:
        return "ip"
    return "domain"


def load_provider(name: str | None = None) -> dict:
    if not PROVIDERS_JSON.exists():
        raise SystemExit(f"[FATAL] 找不到 providers 配置: {PROVIDERS_JSON}")
    providers = json.loads(PROVIDERS_JSON.read_text(encoding="utf-8"))
    enabled = [p for p in providers if p.get("enabled", True)]
    if not enabled:
        raise SystemExit("[FATAL] providers.json 中没有 enabled 的 provider")
    cfg = next((p for p in enabled if p.get("name") == name), None) if name else enabled[0]
    if cfg is None:
        raise SystemExit(f"[FATAL] 找不到 provider: {name}")
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="微步 ThreatBook 连通性验证")
    parser.add_argument("samples", nargs="*", help="自定义指标（ip 值 / 域名值），未给则用默认")
    parser.add_argument("--provider", default=None, help="指定 provider 名称（默认首个 enabled）")
    parser.add_argument("--persist", action="store_true", help="查询后落库 threat_intel（需初始化数据库）")
    args = parser.parse_args()

    samples = [( _guess_type(s), s) for s in args.samples] if args.samples else DEFAULT_SAMPLES

    cfg = load_provider(args.provider)
    key_env = cfg.get("api_key_ref", "")
    env_var = key_env[1:] if key_env.startswith("$") else None
    api_key = os.environ.get(env_var, "") if env_var else key_env
    if not api_key:
        raise SystemExit(
            f"[FATAL] 微步 API key 未配置（环境变量 {env_var} 为空）\n"
            f"        请先设置后再运行：\n"
            f"          PowerShell:  $env:{env_var} = \"你的微步key\"\n"
            f"          cmd:         set {env_var}=你的微步key\n"
            f"        （providers.json 中 api_key_ref={key_env}，运行期自动展开，不落明文）"
        )

    print(f"[INFO] provider = {cfg.get('name')} ({cfg.get('type')})")
    print(f"[INFO] base_url = {cfg.get('base_url')}")
    print(f"[INFO] apikey   = {'*' * min(8, len(api_key))} (已加载, 长度 {len(api_key)})\n")

    provider = create_provider(cfg)

    svc = None
    if args.persist:
        try:
            from app.database import init_db
            init_db()
            from app.services.enrichment_service import get_enrichment_service
            svc = get_enrichment_service()
            print("[INFO] --persist 模式：结果将写入 threat_intel 表\n")
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"[FATAL] 初始化数据库失败: {exc}")

    failures = 0
    for ioc_type, ioc_value in samples:
        print(f"{'=' * 60}")
        print(f"▶ 查询 {ioc_type}: {ioc_value}")
        try:
            if svc is not None:
                result = svc.enrich_ioc(None, ioc_type, ioc_value, provider_name=cfg.get("name"))
            else:
                result = provider.query(ioc_type, ioc_value).to_dict()

            print(f"  [OK] risk_score    = {result.get('risk_score')}")
            print(f"  [OK] judgments     = {result.get('judgments')}")
            print(f"  [OK] threat_level  = {result.get('threat_level')}")
            print(f"  [OK] tags          = {result.get('tags')}")
            print(f"  [OK] confidence    = {result.get('confidence')}")
            print(f"  [OK] raw_summary   = {str(result.get('raw_summary'))[:120]}")
            if svc is not None and result.get("id"):
                print(f"  [OK] 已落库 threat_intel.id = {result.get('id')}")
        except (UnsupportedIocTypeError, ThreatIntelQueryError, QuotaExceededError) as exc:
            failures += 1
            print(f"  [FAIL] {type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  [FAIL] 未知错误 {type(exc).__name__}: {exc}")

    print(f"\n{'=' * 60}")
    if failures == 0:
        print("[RESULT] 全部通过 ✅  微步接口可用，归一化正确。")
        return 0
    print(f"[RESULT] 有 {failures} 项失败 ❌")
    return 1


if __name__ == "__main__":
    sys.exit(main())
