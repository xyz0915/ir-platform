"""规则引擎核心 — 支持 regex/list/threshold/behavior/composite/exists 六种规则类型."""

import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.models.rule import Rule

logger = logging.getLogger(__name__)

# ── 严重级别排序（用于威胁情报回灌时取较高者）───────────────────────
_SEVERITY_RANK: dict = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _max_severity(a: str, b: str) -> str:
    """取两个严重级别中较高的一个."""
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


# ── MatchedRule 默认置信度（按规则类型；设计 §4.4）────────────────────
_CONFIDENCE_DEFAULT: dict = {
    "regex": 0.9,
    "list": 1.0,
    "threshold": 0.8,
    "behavior": 0.7,
    "composite": 0.85,
    "exists": 0.7,
    "attack_chain": 0.95,
}

# 行为模式置信度（兼容旧 rule_matcher 语义，保证实时=分析置信一致）
_BEHAVIOR_CONFIDENCE: dict = {
    "orphan_process": 0.75,
    "child_of_office": 0.85,
    "child_of_browser": 0.80,
    "high_value_path": 0.70,
}

# 严重级别 → 风险分（命中统计 avg_risk_score 用）
_RISK_MAP: dict = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# ── 已知的 C2 框架命令行特征 ──────────────────────────────────────────
_C2_FRAMEWORK_SIGNATURES: list[str] = [
    "cobaltstrike", "metasploit", "empire", "powersploit",
    "sliver", "havoc", "brute_ratel", "nimplant",
    "mythic", "apollo", "ares", "covenant",
    "merlin", "koadic", "pupy", "quasar",
    "darkcomet", "poison_ivy", "gh0st", "plugx",
    "agenttesla", "formbook", "lokibot", "nanocore",
    "remcos", "njrat", "asyncrat", "warzone",
    "azorult", "vidar", "redline", "smokeloader",
]

# ── 引擎支持的 20 种行为模式（白名单）────────────────────────────────
# 导入/创建 behavior 规则时校验 condition.pattern ∈ 此集合，
# 非法值会在写入前被拒绝，避免"拼错静默 False 永不命中"。
BEHAVIOR_PATTERNS: set[str] = {
    "orphan_process",
    "suspicious_parent",
    "unsigned_process",
    "network_scan",
    "credential_dump",
    "uac_bypass",
    "token_manipulation",
    "antivirus_tamper",
    "defense_evasion",
    "lateral_movement",
    "data_exfil",
    "webshell_activity",
    "ransomware_behavior",
    "persistence_wmi",
    "persistence_com_hijack",
    "discovery_recon",
    "dll_sideload",
    "process_chain",
    "time_cluster",
    "short_lived",
    # ── T1 新增：进程树/异常进程检测增强（5 个行为模式）──────────────
    "zombie_process",          # 疑似僵尸/残留进程（数据受限启发式，需人工确认）
    "process_name_spoof",      # 进程名伪装（双扩展名/大小写混淆/相似名/Unicode 同形）
    "suspicious_path",         # 可疑进程路径（temp/appdata/伪装 system32/ADS/UNC）
    "hidden_process",          # 隐蔽/仿冒服务进程（同名不同路径 或 无窗口隐藏）
    "anomalous_net_process",   # 异常网络连接进程（脚本解释器/无签名外连/C2 端口）
    # ── 进程检测加强规则集（P0/P1/P2，T02–T17）────────────────────
    "unsigned_exe",            # 无数字签名 exe（JOIN file_hashes 注入 exe_is_signed）
    "whitelist_derived_chain", # 白名单进程派生的可疑子链（衍生链漏检根因修复）
    "ancestry_chain",          # 多级祖先回溯：祖父为可疑服务/异常
    "parent_pid_spoof",        # 伪造/不可能父 PID（字段级，升级原 parent_pid_spoofing）
    "fileless_residency",      # fileless 内存驻留（path 空/UNC/内存 + 连接/线程）
    "process_respawn",         # 短时间窗口内同 path/cmdline 重复 ≥K（快照近似）
    "revoked_sig",             # 签名被吊销/过期（CRL/OCSP 离线缓存，空库降级）
    "memory_injection",        # 无文件内存注入（reflective/hollowing/远线程）
    "interpreter_mem_pe",      # 脚本解释器内存加载异常 PE（ETW/内存采集）
    "etw_amsi_tamper",         # ETW/AMSI 旁路（事件级）
    "cross_session",           # 跨会话/跨用户父子（需 session 字段）
    "injection_window",        # 注入行为窗口异常（需事件流）
    "vanished_process",        # 快照间出现又消失的进程（需 process_events 表）
    # ── 兼容旧 rule_matcher 行为模式（保证实时=分析语义一致）───────
    "child_of_office",         # Office/文档子进程（旧实时 matcher 行为模式）
    "child_of_browser",        # 浏览器子进程（旧实时 matcher 行为模式）
    "high_value_path",         # 高价值路径（temp/downloads 等）
}

# ── 进程名伪装检测（process_name_spoof）相关常量 ────────────────────────
# 系统进程白名单（不含扩展名，小写），作为大小写/相似名/同形判定的基准
_SYSTEM_PROC_WHITELIST: set[str] = {
    "svchost", "lsass", "services", "csrss", "winlogon", "explorer",
    "taskmgr", "cmd", "powershell", "rundll32", "spoolsv", "msdtc",
    "lsaiso", "fontdrvhost", "smss", "wininit", "lsm",
}
# 已知系统进程（不含 .exe，小写）：孤儿/重生检测中排除，避免海量误报
_SYSTEM_PROCESS_NAMES: set[str] = {
    "system", "secure system", "registry", "system idle process",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "spoolsv.exe",
    "fontdrvhost.exe", "lsaiso.exe", "dwm.exe", "audiodg.exe",
    "memory compression", "conhost.exe", "sihost.exe", "taskhostw.exe",
    "wlms.exe", "logonui.exe", "runtimebroker.exe", "shellexperiencehost.exe",
}
# 双扩展名：可执行/脚本扩展名叠加可执行/脚本
_SPOOF_EXEC_EXTS = (
    "exe", "scr", "bat", "cmd", "pif", "com", "dll",
    "ps1", "vbs", "js", "jar", "msi", "lnk",
)
# 双扩展名：良性文档扩展名叠加可执行（如 evil.jpg.exe）
_SPOOF_BENIGN_EXTS = (
    "jpg", "jpeg", "png", "gif", "bmp", "pdf", "doc", "docx",
    "txt", "xls", "xlsx", "ppt", "pptx", "html", "htm", "zip",
    "rar", "mp3", "mp4",
)
_SPOOF_DOUBLE_EXEC_RE = re.compile(
    r"\.(?:" + "|".join(_SPOOF_EXEC_EXTS) + r")\.(?:" + "|".join(_SPOOF_EXEC_EXTS) + r")$"
)
_SPOOF_BENIGN_EXE_RE = re.compile(
    r"\.(?:" + "|".join(_SPOOF_BENIGN_EXTS) + r")\.(?:" + "|".join(_SPOOF_EXEC_EXTS) + r")$"
)
# 常见 Unicode 同形字符（Cyrillic/Greek 等）→ Latin 映射，辅助识别同形混淆名
_CONFUSABLE_MAP = {
    "а": "a", "е": "e", "о": "o", "с": "c", "р": "p", "х": "x",
    "у": "y", "і": "i", "ѕ": "s", "ԁ": "d", "ԍ": "g", "ո": "n",
    "ї": "i", "ӏ": "l", "ɡ": "g", "ԉ": "n",
}

# ── 可疑路径检测（suspicious_path）相关常量 ────────────────────────────
_SUSPICIOUS_PATH_MARKERS = (
    "\\temp\\", "\\tmp\\", "downloads", "appdata\\roaming", "appdata\\local",
    "programdata", "desktop", "\\public\\", "users\\public",
)
_SUSPICIOUS_PATH_WHITELIST = (
    "c:\\windows\\system32\\",
    "c:\\windows\\syswow64\\",
    "c:\\program files\\",
    "c:\\program files (x86)\\",
)

# ── 可疑父进程（suspicious_parent）默认清单（condition 未配置时回退）──
# 决策3：默认保留原 office 父，新增浏览器/PDF/压缩/IM 父 + 脚本解释器子
_DEFAULT_SUSPICIOUS_PARENTS = [
    "winword", "excel", "powerpnt", "outlook",
    "chrome", "edge", "firefox", "iexplore",
    "acrord32", "foxitreader",
    "winrar", "7z", "bandizip",
    "wechat", "qq", "teamviewer",
]
_DEFAULT_SUSPICIOUS_CHILDREN = ["powershell", "cmd", "wscript", "cscript"]

# ── 异常网络进程（anomalous_net_process）相关常量 ──────────────────────
_ANOMALOUS_NET_INTERPRETERS = {
    "powershell", "cmd", "wscript", "cscript", "certutil", "bitsadmin",
    "mshta", "rundll32", "wmic", "nc", "netcat", "curl", "wget",
    "python", "perl", "ruby",
}
# 业务端口白名单（降低误报）：浏览器/更新/常见服务端口
_BUSINESS_PORTS = {
    80, 443, 53, 22, 3389, 445, 8080, 25, 587, 993, 143, 110, 21, 23,
    3306, 5432, 6379, 27017,
}
# 常见 C2/代理/反弹端口（文档 §3.4；8443 同列于业务与 C2 清单，优先按 C2 判定）
_C2_PORTS = {4444, 8443, 1337, 31337, 6667, 9999, 1080, 5900}

# ── 可疑祖父/父 默认清单（ancestry_chain；T07）────────────────────
# 当进程（脚本解释器/LOLBin）的祖父（或更早祖先）为下列服务进程时，判定链路异常。
_DEFAULT_SUSPICIOUS_GRANDPARENTS = [
    "svchost", "services", "lsass", "winlogon", "spoolsv", "msdtc",
    "smss", "csrss", "wininit", "lsaiso", "fontdrvhost",
]

# ── 吊销/过期签名库（离线 CRL/OCSP 缓存；T17）────────────────────
# 数据来源：CRL/OCSP 离线缓存导出的被吊销/过期 CA 或签名者标识集合。
# 默认从同目录 revoked_ca.json 读取；文件缺失或为空列表时不触发任何命中
# （优雅降级，绝不因缺数据抛异常）。结构：{"revoked_signers": ["CN=...", "..."]}。
_REVOKED_CA_CACHE: Optional[set] = None


def _load_revoked_signers() -> set:
    """加载被吊销/过期的签名者标识集合（CRL/OCSP 离线缓存）.

    从 ``backend/app/rules/revoked_ca.json`` 读取 ``revoked_signers`` 列表。
    任何异常（文件缺失/格式错误）均降级为空集合，保证引擎在缺数据环境下可运行。

    Returns:
        被吊销签名者标识（小写）集合；空集合表示吊销库不可用/为空。
    """
    global _REVOKED_CA_CACHE
    if _REVOKED_CA_CACHE is not None:
        return _REVOKED_CA_CACHE
    revoked: set = set()
    try:
        ca_path = Path(__file__).resolve().parent / "revoked_ca.json"
        if ca_path.exists():
            with open(ca_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for s in (data.get("revoked_signers") or []):
                if s:
                    revoked.add(str(s).lower())
    except Exception as exc:  # noqa: BLE001
        logger.debug("跳过吊销库加载（revoked_ca.json 不可用）: %s", exc)
        revoked = set()
    _REVOKED_CA_CACHE = revoked
    return revoked


def _reset_revoked_cache() -> None:
    """清空吊销库缓存（仅供测试重新加载/降级验证使用）."""
    global _REVOKED_CA_CACHE
    _REVOKED_CA_CACHE = None


# ── 进程名/字符串辅助函数 ───────────────────────────────────────────────

def _norm_proc_name(name: str) -> str:
    """进程名归一化：去常见扩展名并小写，用于白名单/相似名比对.

    Args:
        name: 原始进程名（可能含 .exe 等扩展名与大小写）.

    Returns:
        小写且无扩展名的进程基名；空串返回空串。
    """
    n = (name or "").strip().lower()
    for ext in (".exe", ".scr", ".bat", ".cmd", ".pif", ".com", ".dll",
                ".ps1", ".vbs", ".js", ".sys", ".lnk"):
        if n.endswith(ext):
            n = n[: -len(ext)]
            break
    return n


def _levenshtein(a: str, b: str) -> int:
    """计算两字符串编辑距离（DP，O(n*m)）.

    Args:
        a: 字符串 A.
        b: 字符串 B.

    Returns:
        编辑距离（插入/删除/替换计 1）。
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for ca in a:
        cur = [prev[0] + 1]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[lb]


def _normalize_confusable(text: str) -> str:
    """将常见 Unicode 同形字符替换为对应 Latin 字符（辅助同形混淆识别）.

    Args:
        text: 含可能同形字符的文本.

    Returns:
        同形字符被 Latin 化后的文本（无法映射者保持不变）。
    """
    if not text:
        return text
    return "".join(_CONFUSABLE_MAP.get(ch, ch) for ch in text)


def _name_matches(norm_name: str, configured: set) -> bool:
    """判断归一化进程名是否命中配置清单（支持 python3/pwsh 等版本/变体后缀）.

    Args:
        norm_name: 归一化进程名（小写、无扩展名）。
        configured: 配置的归一化名称集合。

    Returns:
        命中返回 True。
    """
    if norm_name in configured:
        return True
    # 版本/变体后缀：python3 / python3.11 视为 python；剩余部分须全为数字或点
    for c in configured:
        if norm_name.startswith(c) and norm_name[len(c):].replace(".", "").isdigit():
            return True
    return False


def _parse_datetime(value: str) -> Optional["datetime"]:
    """解析常见时间字符串为 datetime，失败返回 None.

    Args:
        value: 时间字符串（支持多种常见格式）.

    Returns:
        datetime 对象，解析失败返回 None。
    """
    if not value:
        return None
    s = str(value).split("+")[0].split("Z")[0]
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ── 正则编译缓存（T-P2-4 性能优化）────────────────────────────────────
# 同一 pattern+flags 只编译一次，避免热路径重复 re.compile。
_REGEX_CACHE: dict = {}

# ── time_cluster 预排序缓存（T-P2-4 性能优化）─────────────────────────
# key = id(all_items)，value = 按 start_time 排序后的 [(datetime, item), ...]
_TC_SORTED_CACHE: dict = {}

# ── field → ioc_type 映射（动态 IOC 引用）────────────────────────────
# list 类规则 condition.field 若为下列网络/主机标识字段，则额外把 iocs 表中
# 对应 ioc_type 且 enabled=1 的指标并入待匹配集合；映射不到的 field 仅匹配自身 values。
# 说明：remote_address 既可能承载 IP 也可能承载域名（如 suspicious_c2_domain 规则），
# 此处按"最贴近威胁语义"的口径映射为 ip（IP 类 IOC 命中更精确），域名类 IOC 由
# domain/host/url 字段各自的规则覆盖，互不干扰。
FIELD_TO_IOC_TYPE: dict = {
    # IP 类
    "remote_address": "ip",
    "remote_ip": "ip",
    "src_ip": "ip",
    "dst_ip": "ip",
    # 域名 / URL 类（按 field 名分别映射到 domain 或 url）
    "domain": "domain",
    "host": "domain",
    "url": "url",
    # 文件哈希类
    "file_hash": "hash",
    "sha256": "hash",
    "hash": "hash",
    # 进程 exe 哈希（T03：按 path JOIN 已采集的 file_hashes 注入 exe_sha256，
    # 经 FIELD_TO_IOC_TYPE 动态并入主机 iocs.hash，复用 _match_list 既有机制）
    "exe_sha256": "hash",
    # 证书类
    "cert": "cert",
    "certificate": "cert",
}


def validate_behavior_pattern(pattern: str) -> bool:
    """校验行为模式是否属于引擎支持的 20 种白名单.

    Args:
        pattern: behavior 规则的 condition.pattern.

    Returns:
        合法返回 True，否则 False.
    """
    return pattern in BEHAVIOR_PATTERNS


class RuleEngine:
    """规则引擎.

    支持六种规则类型：regex、list、threshold、behavior、composite、exists.
    """

    @staticmethod
    def load_rules(category: Optional[str] = None) -> list:
        """从数据库加载启用的规则.

        Args:
            category: 规则类别过滤（可选）.

        Returns:
            规则列表.
        """
        if category:
            return Rule.list(category=category, enabled=True)
        return Rule.list_enabled()

    @staticmethod
    def load_rules_by_ids(rule_ids: list[int]) -> list:
        """按规则ID列表加载规则（策略激活时使用）.

        Args:
            rule_ids: 规则 ID 列表.

        Returns:
            规则列表.
        """
        if not rule_ids:
            return []
        return Rule.list_by_ids(rule_ids)

    @staticmethod
    def _compile_regex(pattern: str, flags: int) -> "re.Pattern":
        """编译并缓存正则表达式（T-P2-4 性能优化）.

        Args:
            pattern: 正则字符串.
            flags: re 标志位.

        Returns:
            已编译的 regex 对象.
        """
        cache_key = (pattern, flags)
        compiled = _REGEX_CACHE.get(cache_key)
        if compiled is None:
            compiled = re.compile(pattern, flags)
            _REGEX_CACHE[cache_key] = compiled
        return compiled

    @staticmethod
    def _build_sorted_items(all_items: list) -> list:
        """将 all_items 按 start_time 排序，供 time_cluster 二分计数（T-P2-4）.

        Args:
            all_items: 所有进程数据项列表.

        Returns:
            [(datetime, item), ...] 已排序列表；无法解析时间的项排在最前（datetime.min）.
        """
        from datetime import datetime

        cache_key = id(all_items)
        cached = _TC_SORTED_CACHE.get(cache_key)
        if cached is not None:
            return cached

        time_formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y/%m/%d %H:%M:%S",
        ]

        def _parse(ts: str):
            if not ts:
                return None
            s = str(ts).split("+")[0].split("Z")[0]
            for fmt in time_formats:
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue
            return None

        parsed = []
        for item in all_items:
            if not isinstance(item, dict):
                continue
            parsed.append((_parse(item.get("start_time", "")), item))
        parsed.sort(key=lambda x: (x[0] is None, x[0] or datetime.min))
        _TC_SORTED_CACHE[cache_key] = parsed
        return parsed

    @staticmethod
    def _load_iocs_by_type() -> dict:
        """从 DB 一次性加载全部 enabled=1 的 IOC，按 ioc_type 分组为集合.

        返回结构: {"ip": {"1.2.3.4", ...}, "domain": {...}, ...}

        - 仅在 evaluate 入口调用一次，避免逐条数据查 DB（性能）。
        - 不引入持久内存缓存，每次评估实时读取，保证 iocs 表变更立即可生效。
        - 任何 DB/导入异常都被吞掉并返回空字典，保证引擎在缺表/缺库环境下仍可降级运行。

        Returns:
            按类型分组的 IOC 指标值集合字典；出错时返回空字典。
        """
        try:
            from app.models.ioc import Ioc
        except Exception as exc:  # noqa: BLE001
            logger.debug("跳过 IOC 动态加载（Ioc 模型不可用）: %s", exc)
            return {}

        try:
            rows = Ioc.list()
        except Exception as exc:  # noqa: BLE001
            # DB 未初始化 / 缺表 / 连接异常等情况均降级为空集合
            logger.debug("跳过 IOC 动态加载（读取 iocs 失败）: %s", exc)
            return {}

        by_type: dict = {}
        for r in rows:
            if not r.get("enabled"):
                continue
            ioc_type = r.get("ioc_type")
            value = r.get("ioc_value")
            if not ioc_type or value is None:
                continue
            by_type.setdefault(ioc_type, set()).add(value)
        return by_type

    @staticmethod
    def _load_threat_level_by_value() -> dict:
        """加载威胁情报平台回灌所需的 {value_lower: {level, provider}} 映射.

        仅取每个 indicator 最新一条记录（按 queried_at 倒序去重保留首条），
        且该记录的 judgments 必须包含 malicious/suspicious：
          - malicious → level=high
          - suspicious → level=medium

        任何 DB/导入异常都被吞掉并返回空字典，保证引擎在缺表/缺库环境下仍可降级运行。

        Returns:
            按指标值（小写）分组的威胁等级字典；出错时返回空字典。
        """
        try:
            from app.database import get_connection
        except Exception as exc:  # noqa: BLE001
            logger.debug("跳过威胁情报回灌加载（database 不可用）: %s", exc)
            return {}

        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT ioc_value, provider, judgments, queried_at
                    FROM threat_intel
                    ORDER BY ioc_value, queried_at DESC, id DESC
                    """
                ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.debug("跳过威胁情报回灌加载（读取 threat_intel 失败）: %s", exc)
            return {}

        result: dict = {}
        seen: set = set()
        for row in rows:
            key = (row["ioc_value"] or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            raw_j = row["judgments"]
            if isinstance(raw_j, str) and raw_j:
                try:
                    judgments = json.loads(raw_j)
                except (json.JSONDecodeError, TypeError):
                    judgments = []
            else:
                judgments = []
            if not isinstance(judgments, list):
                judgments = []
            jset = {str(j).lower() for j in judgments}
            level = None
            if "malicious" in jset:
                level = "high"
            elif "suspicious" in jset:
                level = "medium"
            if level:
                result[key] = {"level": level, "provider": row["provider"]}
        return result

    @staticmethod
    def _record_ti_hit(global_context: Optional[dict], value_lower: str, item: dict) -> None:
        """在 list 类规则命中时，记录该命中值与威胁情报等级的关联（供 evaluate 回灌）.

        Args:
            global_context: 全局上下文（含 threat_level_by_value）。
            value_lower: 命中的指标值（已小写）。
            item: 被检测的数据项（用于按 id 归集命中）。
        """
        if not global_context:
            return
        tl = global_context.get("threat_level_by_value") or {}
        info = tl.get(value_lower)
        if not info:
            return
        ti_hits = global_context.setdefault("_ti_hits", {})
        ti_hits.setdefault(id(item), []).append({
            "value": value_lower,
            "level": info["level"],
            "provider": info.get("provider"),
        })

    @staticmethod
    def evaluate(
        data_items: list,
        rules: list,
        global_context: Optional[dict] = None,
        policy: Optional["DetectionPolicy"] = None,
    ) -> list:
        """对数据项列表执行统一规则匹配（单一引擎：实时=分析共用）.

        判定顺序（设计 §8）：
          ① 候选加载 → ② 抑制检查 is_suppressed → ③ match_rule →
          ④ 白名单精确检查 is_whitelisted_precise → ⑤ 误报模式检查
          FalsePositivePattern.match → ⑥ 真实命中产 MatchedRule。

        抑制为最宽门控（命中则整条规则不告警），命中点再做实体级精确豁免，
        最后误报模式收口。所有产出的 MatchedRule 均带 ``gated_by`` 标记
        （null | "suppression" | "whitelist" | "false_positive"）。

        Args:
            data_items: 待检测的数据项列表（to_engine_item 扁平 dict）。
            rules: 规则列表。
            global_context: 全局上下文（host_id / process_map / all_items / connections）。
            policy: 检测策略门控（实时与分析共用同一实例保证一致）。

        Returns:
            MatchedRule 字典列表（含被门控排除的命中，gated_by 标记其被排除原因）。
        """
        if global_context is None:
            global_context = {}

        # 确保 datetime 在本地作用域可用
        from datetime import datetime

        if policy is None:
            from app.rules.detection_policy import DetectionPolicy
            policy = DetectionPolicy()

        # ── 动态 IOC 引用：入口一次性加载 ──
        global_context["iocs_by_type"] = RuleEngine._load_iocs_by_type()

        # ── 威胁情报平台回灌 ──
        if settings.ENABLE_THREAT_INTEL_ENRICHMENT:
            global_context["threat_level_by_value"] = RuleEngine._load_threat_level_by_value()
        else:
            global_context["threat_level_by_value"] = {}
        global_context["_ti_hits"] = {}

        # 预排序 all_items 供 time_cluster 二分计数
        if global_context and isinstance(global_context.get("all_items"), list):
            sorted_items = RuleEngine._build_sorted_items(global_context["all_items"])
            global_context["_tc_sorted"] = sorted_items
            global_context["_tc_dts"] = [
                d if d is not None else datetime.min for d, _ in sorted_items
            ]

        host_id = global_context.get("host_id")
        # ── 门控结果缓存（进程内复用，避免逐事件重复 DB 查询）──
        suppressed_cache: dict = global_context.setdefault("_suppressed_cache", {})
        fp_cache: dict = global_context.setdefault("_fp_cache", {})

        matches: list = []
        per_item_rules = [r for r in rules if r.get("rule_type") != "attack_chain"]
        attack_chain_rules = [r for r in rules if r.get("rule_type") == "attack_chain"]

        for item in data_items:
            if not isinstance(item, dict):
                continue
            for rule in per_item_rules:
                # ③ 匹配
                if not RuleEngine.match_rule(item, rule, global_context=global_context):
                    continue
                # 影子模式：仅计数不告警（不进入门控，保持原行为）
                if rule.get("is_shadow"):
                    rule["_shadow_hit_updated"] = True
                    rule["shadow_hit_count"] = rule.get("shadow_hit_count", 0) + 1
                    _shadow_samples = rule.setdefault("_shadow_sample_hits", [])
                    if len(_shadow_samples) < 20:
                        _shadow_samples.append(
                            {k: item.get(k) for k in ("id","event_type","event_label",
                               "process_name","source_ip","timestamp","hostname","host_id") if k in item}
                        )
                    continue
                # ② 抑制检查（规则级，最宽）
                if RuleEngine._is_suppressed(rule, host_id, suppressed_cache):
                    matches.append(RuleEngine._make_matched_rule(item, rule, global_context, gated_by="suppression"))
                    continue
                # ④ 白名单精确检查（实体级）
                if RuleEngine._is_whitelisted(rule, item):
                    matches.append(RuleEngine._make_matched_rule(item, rule, global_context, gated_by="whitelist"))
                    continue
                # ⑤ 误报模式检查（自增 hit_count，不告警）
                if RuleEngine._is_false_positive(rule, item, host_id, fp_cache):
                    matches.append(RuleEngine._make_matched_rule(item, rule, global_context, gated_by="false_positive"))
                    continue
                # ⑥ 真实命中
                matches.append(RuleEngine._make_matched_rule(item, rule, global_context, gated_by=None))

        # ── 攻击链关联检测（主机级，实时=分析共用）──
        if policy.enable_attack_chain and attack_chain_rules:
            if host_id is not None:
                host_events = RuleEngine._build_host_events(global_context)
                for ac_rule in attack_chain_rules:
                    if ac_rule.get("is_shadow"):
                        ac_rule["_shadow_hit_updated"] = True
                        ac_rule["shadow_hit_count"] = ac_rule.get("shadow_hit_count", 0) + 1
                        continue
                    if RuleEngine._is_suppressed(ac_rule, host_id, suppressed_cache):
                        continue
                    result = RuleEngine._match_attack_chain(ac_rule, global_context, host_events)
                    if result:
                        ac_match = {
                            "item": {
                                "host_id": host_id,
                                "_attack_chain": True,
                                "attack_chain_steps": result["steps"],
                            },
                            "rule": ac_rule,
                            "rule_id": ac_rule.get("id"),
                            "rule_name": ac_rule.get("name", ""),
                            "rule_type": "attack_chain",
                            "category": ac_rule.get("category"),
                            "severity": "critical",
                            "confidence": _CONFIDENCE_DEFAULT.get("attack_chain", 0.95),
                            "reason": result["reason"],
                            "matched_fields": {},
                            "matched_dimension": None,
                            "attack_chain": result,
                            "gated_by": None,
                        }
                        # T-P1-4: 攻击链命中自动 Playbook（critical 必走 HITL）
                        try:
                            from app.services.rule_hit_response import RuleHitResponseService
                            pb_result = RuleHitResponseService.maybe_trigger(ac_match)
                            ac_match["auto_playbook"] = {
                                "auto_playbook_triggered": pb_result.get("auto_playbook_triggered", False),
                                "triggered_playbook_id": pb_result.get("triggered_playbook_id"),
                                "trigger_message": pb_result.get("trigger_message"),
                            }
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("AttackChain AutoPlaybook 安全降级: %s", exc)
                            ac_match["auto_playbook"] = {
                                "auto_playbook_triggered": False,
                                "triggered_playbook_id": None,
                                "trigger_message": f"降级: {exc}",
                            }
                        matches.append(ac_match)
                        ac_rule["_hit_updated"] = True
                        ac_rule["hit_count"] = ac_rule.get("hit_count", 0) + 1
                        ac_rule["last_hit_at"] = datetime.now().isoformat()
                        hit_cnt2 = ac_rule["hit_count"]
                        cur_avg2 = ac_rule.get("avg_risk_score", 0.0) or 0.0
                        ac_rule["avg_risk_score"] = (cur_avg2 * (hit_cnt2 - 1) + 4) / hit_cnt2
            else:
                logger.debug("存在 attack_chain 规则但 global_context 缺少 host_id，跳过攻击链评估")

        # ── 批量更新规则命中统计到 DB ──
        RuleEngine._update_rule_stats(rules)

        return matches

    @staticmethod
    def _update_rule_stats(rules: list) -> None:
        """批量更新规则命中统计到 DB（#10/#16）.

        只更新标记了 ``_hit_updated`` 的规则，避免不必要的 DB 写入。
        在 ``evaluate()`` 末尾统一调用，降低 DB 压力至每轮评估一次批量 UPDATE。

        Args:
            rules: 本次评估的规则列表（已原地更新 hit_count/last_hit_at/avg_risk_score）.
        """
        updated: list[tuple] = []
        shadow_updated: list[tuple] = []
        for rule in rules:
            if rule.get("_hit_updated"):
                updated.append((
                    rule.get("hit_count", 0),
                    rule.get("last_hit_at"),
                    rule.get("avg_risk_score", 0.0),
                    rule.get("name", ""),
                ))
            if rule.get("_shadow_hit_updated"):
                shadow_updated.append((
                    rule.get("shadow_hit_count", 0),
                    rule.get("name", ""),
                ))
        if not updated and not shadow_updated:
            return
        try:
            from app.database import get_connection
            with get_connection() as conn:
                if updated:
                    conn.executemany(
                        """
                        UPDATE rules SET
                            hit_count = ?,
                            last_hit_at = ?,
                            avg_risk_score = ?
                        WHERE name = ?
                        """,
                        updated,
                    )
                if shadow_updated:
                    conn.executemany(
                        """
                        UPDATE rules SET shadow_hit_count = ? WHERE name = ?
                        """,
                        shadow_updated,
                    )
            logger.debug(
                "Batch updated %d rule stats (%d shadow)", len(updated), len(shadow_updated)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("批量更新规则命中统计失败: %s", exc)

    @staticmethod
    def match_rule(data_item: dict, rule: dict, global_context: Optional[dict] = None) -> bool:
        """检查单个数据项是否匹配规则（通过 MatcherRegistry 分发）.

        Args:
            data_item: 数据项字典.
            rule: 规则字典.
            global_context: 全局上下文（可选），用于 behavior 模式检测.

        Returns:
            是否匹配.
        """
        rule_type = rule.get("rule_type", "")
        condition = rule.get("condition", {})
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except json.JSONDecodeError:
                return False

        from app.rules.matchers.registry import MatcherRegistry
        matched = MatcherRegistry.dispatch(rule_type, data_item, condition, global_context)
        if matched and rule_type == "behavior":
            data_item["_matched_dimension"] = RuleEngine._infer_dimension(
                condition.get("pattern", "") if isinstance(condition, dict) else ""
            )
        return matched

    @staticmethod
    def load_rules_by_categories(categories: list) -> list:
        """按多个类别加载启用的规则（实时候选预筛用）.

        Args:
            categories: 规则类别列表（如 ["process", "behavior"]）.

        Returns:
            规则字典列表（condition 已解析，enabled 已归一化为 bool）.
        """
        if not categories:
            return []
        from app.models.rule import Rule
        return Rule.list_categories(categories, enabled=True)

    @staticmethod
    def _is_suppressed(rule: dict, host_id, cache: dict) -> bool:
        """抑制检查（缓存复用，避免逐事件重复 DB 查询）."""
        name = rule.get("name")
        if not name:
            return False
        key = (name, host_id)
        if key in cache:
            return cache[key]
        try:
            from app.models.rule_suppression import RuleSuppression
            result = bool(RuleSuppression.is_suppressed(name, host_id or 0))
        except Exception as exc:
            logger.debug("抑制检查失败（降级为不抑制）: %s", exc)
            result = False
        cache[key] = result
        return result

    @staticmethod
    def _is_whitelisted(rule: dict, item: dict) -> bool:
        """白名单精确检查（调用 WhitelistService.is_whitelisted_precise）."""
        try:
            from app.services.whitelist_service import WhitelistService
            return bool(WhitelistService.is_whitelisted_precise(rule, item))
        except Exception as exc:
            logger.debug("白名单检查失败（降级为不豁免）: %s", exc)
            return False

    @staticmethod
    def _is_false_positive(rule: dict, item: dict, host_id, cache: dict) -> bool:
        """误报模式检查（命中则自增 hit_count，cache 复用）."""
        name = rule.get("name")
        if not name:
            return False
        source_process = str(item.get("name") or item.get("process_name") or "")
        key = (name, source_process, host_id)
        if key in cache:
            return cache[key]
        try:
            from app.models.false_positive import FalsePositivePattern
            result = bool(FalsePositivePattern.match(name, source_process, host_id or 0))
        except Exception as exc:
            logger.debug("误报模式检查失败（降级为不误报）: %s", exc)
            result = False
        cache[key] = result
        return result

    @staticmethod
    def _make_matched_rule(item: dict, rule: dict, global_context: dict, gated_by: Optional[str]) -> dict:
        """构造 MatchedRule 字典（含门控标记、置信度、威胁情报回灌）.

        T-P1-4: 若为真实命中（gated_by=None）且置信度≥阈值，
        自动触发 Playbook（含 HITL 审批），通过 try/except 安全降级。
        """
        from app.rules.matched_rule import MatchedRule
        severity = rule.get("severity", "medium")
        reason = RuleEngine._build_reason(item, rule)
        ti_hits = global_context.get("_ti_hits", {}).get(id(item), [])
        for hit in ti_hits:
            if hit.get("level") == "high":
                severity = _max_severity(severity, "high")
                reason += "【威胁情报平台判黑】"
            elif hit.get("level") == "medium":
                reason += "【威胁情报平台可疑】"
        confidence = RuleEngine._confidence_for(rule)
        mr = MatchedRule(
            item=item,
            rule=rule,
            rule_id=rule.get("id"),
            rule_name=rule.get("name", ""),
            rule_type=rule.get("rule_type", ""),
            category=rule.get("category"),
            severity=severity,
            confidence=confidence,
            reason=reason,
            matched_fields=RuleEngine._extract_matched_fields(item, rule),
            matched_dimension=item.get("_matched_dimension") if rule.get("rule_type") == "behavior" else None,
            attack_chain=None,
            gated_by=gated_by,
        )
        if gated_by is None:
            rule["_hit_updated"] = True
            rule["hit_count"] = rule.get("hit_count", 0) + 1
            rule["last_hit_at"] = datetime.now().isoformat()
            hit_cnt = rule["hit_count"]
            cur_avg = rule.get("avg_risk_score", 0.0) or 0.0
            rule["avg_risk_score"] = (cur_avg * (hit_cnt - 1) + _RISK_MAP.get(severity, 2)) / hit_cnt

        # ── T-P1-4: 自动 Playbook 触发（高置信真实命中） ──
        # maybe_trigger 内部判断置信度阈值，此处对所有非门控真实命中尝试触发
        if gated_by is None:
            try:
                from app.services.rule_hit_response import RuleHitResponseService
                pb_result = RuleHitResponseService.maybe_trigger(mr.to_dict())
                mr.auto_playbook = {
                    "auto_playbook_triggered": pb_result.get("auto_playbook_triggered", False),
                    "triggered_playbook_id": pb_result.get("triggered_playbook_id"),
                    "trigger_message": pb_result.get("trigger_message"),
                }
            except Exception as exc:  # noqa: BLE001
                logger.debug("AutoPlaybook 安全降级（make_matched_rule）: %s", exc)
                mr.auto_playbook = {
                    "auto_playbook_triggered": False,
                    "triggered_playbook_id": None,
                    "trigger_message": f"降级: {exc}",
                }

        return mr.to_dict()

    @staticmethod
    def _confidence_for(rule: dict) -> float:
        """根据规则类型与行为模式计算置信度."""
        rt = rule.get("rule_type", "")
        if rt == "behavior":
            cond = rule.get("condition") or {}
            if isinstance(cond, str):
                try:
                    cond = json.loads(cond)
                except (json.JSONDecodeError, TypeError):
                    cond = {}
            if isinstance(cond, dict):
                pat = cond.get("pattern", "")
                if pat in _BEHAVIOR_CONFIDENCE:
                    return _BEHAVIOR_CONFIDENCE[pat]
            return 0.7
        return _CONFIDENCE_DEFAULT.get(rt, 0.8)

    @staticmethod
    def _extract_matched_fields(item: dict, rule: dict) -> dict:
        """从触发命中中提取匹配字段快照（供 MatchedRule.matched_fields 使用）."""
        cond = rule.get("condition") or {}
        if isinstance(cond, str):
            try:
                cond = json.loads(cond)
            except (json.JSONDecodeError, TypeError):
                cond = {}
        fields: dict = {}
        field = cond.get("field") if isinstance(cond, dict) else None
        if field is not None and item.get(field) is not None:
            fields[field] = str(item.get(field))[:200]
        if rule.get("rule_type") == "behavior":
            for f in ("name", "path", "command_line", "ppid", "parent_name", "process_name"):
                if item.get(f) is not None and f not in fields:
                    fields[f] = str(item.get(f))[:200]
        return fields

    # ── 正则匹配 ────────────────────────────────────────────────────────

    @staticmethod
    def _match_regex(data_item: dict, condition: dict) -> bool:
        """正则匹配.

        Condition 格式: {"field": "command_line", "pattern": "powershell.*-enc", "flags": "ignorecase"}
        """
        field = condition.get("field", "")
        pattern = condition.get("pattern", "")
        flags_str = condition.get("flags", "")

        value = str(data_item.get(field, ""))
        if not value or not pattern:
            return False

        flags = 0
        if "ignorecase" in flags_str:
            flags |= re.IGNORECASE
        if "multiline" in flags_str:
            flags |= re.MULTILINE

        try:
            return bool(RuleEngine._compile_regex(pattern, flags).search(value))
        except re.error:
            return False

    # ── 列表匹配 ────────────────────────────────────────────────────────

    @staticmethod
    def _match_list(data_item: dict, condition: dict, global_context: Optional[dict] = None) -> bool:
        """黑名单匹配.

        Condition 格式: {"field": "remote_address", "values": ["1.2.3.4", "5.6.7.8"], "match_mode": "exact"}

        动态 IOC 引用：若 condition.field 命中 FIELD_TO_IOC_TYPE 映射，则额外把
        global_context["iocs_by_type"][对应类型] 中 enabled=1 的指标并入待匹配集合
        （与 rule.condition.values 取并集）。iocs 表为空或该类型无数据时仅匹配 values，
        完全向后兼容。不修改原始 condition.values。
        """
        field = condition.get("field", "")
        base_values = condition.get("values") or []
        if not isinstance(base_values, list):
            base_values = [base_values]
        match_mode = condition.get("match_mode", "exact")

        # ── 合并 iocs 表动态指标（与 values 取并集）─────────────────
        merged_values: list = list(base_values)
        if global_context:
            iocs_by_type = global_context.get("iocs_by_type") or {}
            if iocs_by_type:
                ioc_type = FIELD_TO_IOC_TYPE.get(field)
                if ioc_type and ioc_type in iocs_by_type:
                    dyn = iocs_by_type[ioc_type]
                    if dyn:
                        merged_values = merged_values + list(dyn)

        value = data_item.get(field, "")
        if not value or not merged_values:
            return False

        value_str = str(value).lower()
        for v in merged_values:
            v_str = str(v).lower()
            if match_mode == "exact":
                if value_str == v_str:
                    RuleEngine._record_ti_hit(global_context, v_str, data_item)
                    return True
            elif match_mode == "contains":
                if v_str in value_str:
                    RuleEngine._record_ti_hit(global_context, v_str, data_item)
                    return True
            elif match_mode == "startswith":
                if value_str.startswith(v_str):
                    RuleEngine._record_ti_hit(global_context, v_str, data_item)
                    return True
        return False

    # ── 阈值匹配 ────────────────────────────────────────────────────────

    @staticmethod
    def _match_threshold(data_item: dict, condition: dict) -> bool:
        """阈值检测.

        Condition 格式: {"field": "connection_count", "operator": ">", "value": 50}
        """
        field = condition.get("field", "")
        operator = condition.get("operator", ">")
        threshold_value = condition.get("value", 0)

        value = data_item.get(field, 0)
        try:
            value = float(value)
        except (ValueError, TypeError):
            return False

        if operator == ">":
            return value > threshold_value
        elif operator == ">=":
            return value >= threshold_value
        elif operator == "<":
            return value < threshold_value
        elif operator == "<=":
            return value <= threshold_value
        elif operator == "==":
            return value == threshold_value
        elif operator == "!=":
            return value != threshold_value
        return False

    # ── 存在性检查 ──────────────────────────────────────────────────────

    @staticmethod
    def _match_exists(data_item: dict, condition: dict) -> bool:
        """检查字段是否存在且非空.

        Condition 格式: {"field": "remote_address"}

        Args:
            data_item: 数据项字典.
            condition: 条件字典，必须包含 field 字段.

        Returns:
            字段存在且非空返回 True.
        """
        field = condition.get("field", "")
        if not field:
            return False
        value = data_item.get(field)
        if value is None:
            return False
        if isinstance(value, str) and value.strip() == "":
            return False
        if isinstance(value, (list, dict)) and len(value) == 0:
            return False
        return True

    # ── 组合条件匹配 ──────────────────────────────────────────────────────

    @staticmethod
    def _match_composite(data_item: dict, condition: dict, global_context: Optional[dict] = None) -> bool:
        """组合条件匹配 — 支持 AND/OR 逻辑递归求值.

        Condition 格式::

            {
                "logic": "AND",
                "sub_rules": [
                    {"type": "regex", "field": "command_line", "pattern": "mimikatz"},
                    {"type": "exists", "field": "remote_address"}
                ]
            }

        子规则支持任意嵌套深度，type 可以是:
        regex, list, threshold, behavior, composite, exists

        Args:
            data_item: 数据项字典.
            condition: 组合条件字典.

        Returns:
            组合匹配结果.
        """
        logic = condition.get("logic", "AND").upper()
        sub_rules = condition.get("sub_rules", [])

        if not sub_rules:
            return False

        results: list[bool] = []
        for sub in sub_rules:
            sub_type = sub.get("type", "")
            try:
                if sub_type == "regex":
                    results.append(RuleEngine._match_regex(data_item, sub))
                elif sub_type == "list":
                    results.append(RuleEngine._match_list(data_item, sub, global_context=global_context))
                elif sub_type == "threshold":
                    results.append(RuleEngine._match_threshold(data_item, sub))
                elif sub_type == "behavior":
                    results.append(RuleEngine._match_behavior(data_item, sub, global_context=global_context))
                elif sub_type == "composite":
                    results.append(RuleEngine._match_composite(data_item, sub, global_context=global_context))
                elif sub_type == "exists":
                    results.append(RuleEngine._match_exists(data_item, sub))
                else:
                    logger.warning("Unknown sub_rule type: %s", sub_type)
                    results.append(False)
            except Exception as exc:
                logger.warning(
                    "Error evaluating sub_rule type=%s: %s", sub_type, exc
                )
                results.append(False)

        if logic == "AND":
            return all(results)
        elif logic == "OR":
            return any(results)
        else:
            logger.warning("Unknown composite logic: %s", logic)
            return False

    # ── 行为模式检测 ──────────────────────────────────────────────────────

    # #19 DIMENSION_MAP: 根据 pattern 名称前缀自动推断维度
    _DIMENSION_MAP = {
        "orphan": "process", "suspicious_parent": "process", "unsigned": "process",
        "network": "network", "scan": "network",
        "persistence": "persistence", "process_respawn": "process",
        "process_name": "process", "suspicious_path": "process",
        "hidden": "process", "anomalous_net": "connection",
        "zombie": "process", "ancestry": "process",
        "parent_pid": "process", "memory": "process",
        "cross_session": "process", "injection": "process",
        "vanished": "process", "short_lived": "process",
        "time_cluster": "process", "token": "process",
        "credential": "process", "uac": "process",
        "antivirus": "process", "defense": "process",
        "lateral": "process", "data_exfil": "connection",
        "webshell": "network", "ransomware": "process",
        "discovery": "process", "dll_sideload": "process",
        "revoked": "process", "whitelist": "process",
        "interpreter": "process", "etw": "process",
        "injection_window": "process",
    }

    @staticmethod
    def _infer_dimension(pattern: str) -> str:
        """根据 pattern 前缀推断行为维度."""
        for prefix, dim in RuleEngine._DIMENSION_MAP.items():
            if pattern.startswith(prefix):
                return dim
        return "unknown"

    @staticmethod
    def _match_behavior(data_item: dict, condition: dict, global_context: Optional[dict] = None) -> bool:
        """行为模式检测.

        Condition 格式: {"pattern": "orphan_process", "description": "..."}

        支持 20 种行为模式:

        ======================= ==========================================
        模式名                   说明
        ======================= ==========================================
        orphan_process          无父进程或父进程已退出
        suspicious_parent       可疑父进程启动脚本解释器
        unsigned_process        非系统目录进程
        network_scan            网络扫描行为
        credential_dump         凭据导出 (LSASS/SAM)
        uac_bypass              UAC 绕过
        token_manipulation      Token 操作
        antivirus_tamper        杀软干扰/禁用
        defense_evasion         日志清除/时间戳篡改
        lateral_movement        横向移动
        data_exfil              数据外传
        webshell_activity       WebShell 特征
        ransomware_behavior     勒索软件行为
        persistence_wmi         WMI 持久化
        persistence_com_hijack  COM 劫持持久化
        discovery_recon         系统信息探测
        dll_sideload            DLL 侧加载
        process_chain           进程链攻击路径
        time_cluster            时间聚类异常
        short_lived             短存活 Shell 进程
        zombie_process          疑似僵尸/残留进程（启发式，需人工确认）
        process_name_spoof      进程名伪装（双扩展名/大小写/相似名/同形）
        suspicious_path         可疑进程路径（temp/appdata/伪装system32/ADS）
        hidden_process          隐蔽/仿冒服务进程
        anomalous_net_process   异常网络连接进程（脚本解释器/无签名外连/C2端口）
        ======================= ==========================================
        """
        pattern: str = condition.get("pattern", "")

        # #19: 在匹配前清除旧标记，匹配成功时注入维度
        data_item.pop("_matched_dimension", None)

        # ── 原有 4 个模式 ──────────────────────────────────────────
        if pattern == "orphan_process":
            # 上下文敏感孤儿判定（兼容新旧两套测试契约）：
            # - 无进程树上下文（global_context 未提供 / process_map 为空，如旧版
            #   单独 match_rule 调用）：沿用旧启发式 —— 仅 ppid==0（System Idle）
            #   视为孤儿，其余正常数值 PID 均不误报。
            # - 有进程树上下文：父 PID 不在本机进程列表（父已退出/伪造）→ 孤儿；
            #   系统/空闲父（0/1/4）与缺失父统一排除，避免海量误报（§2.1/决策2）。
            #   已知 Windows 系统进程（csrss/wininit/winlogon/services/smss）排除。
            proc_name = str(data_item.get("name", "")).lower()
            if proc_name in _SYSTEM_PROCESS_NAMES:
                return False
            ppid = data_item.get("ppid", 0)
            process_map = (global_context or {}).get("process_map", {})
            if ppid is None or ppid in (0, 1, 4):
                if not process_map:
                    return ppid == 0
                return False
            if not process_map:
                return False
            return ppid not in process_map

        elif pattern == "suspicious_parent":
            # 改造（决策3）：condition 驱动。
            # 若规则 condition 配置 parents/children 则使用，否则回退扩展默认清单
            # （office + 浏览器 + PDF + 压缩 + IM 父，脚本解释器子）。
            parent_name = str(data_item.get("parent_name", ""))
            child_name = str(data_item.get("name", ""))
            cond_parents = condition.get("parents")
            cond_children = condition.get("children")
            if cond_parents:
                suspicious_parents = {_norm_proc_name(p) for p in cond_parents}
            else:
                suspicious_parents = {
                    _norm_proc_name(p) for p in _DEFAULT_SUSPICIOUS_PARENTS
                }
            if cond_children:
                suspicious_children = {_norm_proc_name(c) for c in cond_children}
            else:
                suspicious_children = {
                    _norm_proc_name(c) for c in _DEFAULT_SUSPICIOUS_CHILDREN
                }
            return (
                _name_matches(_norm_proc_name(parent_name), suspicious_parents)
                and _name_matches(_norm_proc_name(child_name), suspicious_children)
            )

        elif pattern == "unsigned_process":
            path = str(data_item.get("path", "")).lower()
            system_dirs = [
                "c:\\windows\\system32",
                "c:\\windows\\syswow64",
                "/usr/bin",
                "/usr/sbin",
            ]
            return path and not any(d in path for d in system_dirs)

        elif pattern == "network_scan":
            connections = data_item.get("connections", [])
            if isinstance(connections, list):
                unique_ips: set[str] = set()
                for conn in connections:
                    remote = conn.get("remote_address", "")
                    if remote:
                        unique_ips.add(remote)
                return len(unique_ips) > 20
            return False

        # ── 凭据导出: LSASS/SAM dump ─────────────────────────────
        elif pattern == "credential_dump":
            name = str(data_item.get("name", "")).lower()
            cmd = str(data_item.get("command_line", "")).lower()
            # LSASS dump tools
            lsass_tools = [
                "procdump", "mimikatz", "lsass", "sqldumper",
                "comsvcs.dll", "rundll32.exe",
            ]
            for tool in lsass_tools:
                if tool in name or tool in cmd:
                    return True
            # SAM / SYSTEM hive access
            sam_keywords = [
                "sam", "system", "security",
                "hklm\\sam", "hklm\\security",
                "reg save", "ntds.dit",
            ]
            if any(kw in cmd for kw in sam_keywords):
                return True
            return False

        # ── UAC 绕过 ──────────────────────────────────────────────
        elif pattern == "uac_bypass":
            cmd = str(data_item.get("command_line", "")).lower()
            path = str(data_item.get("path", "")).lower()
            uac_indicators = [
                "fodhelper.exe", "computerdefaults.exe",
                "eventvwr.exe", "sdclt.exe",
                "slui.exe", "winsat.exe",
                "wsreset.exe", "cmstp.exe",
                "hkcu\\software\\classes\\ms-settings",
                "shell\\open\\command",
            ]
            for indicator in uac_indicators:
                if indicator in cmd or indicator in path:
                    return True
            return False

        # ── Token 操作 ────────────────────────────────────────────
        elif pattern == "token_manipulation":
            name = str(data_item.get("name", "")).lower()
            cmd = str(data_item.get("command_line", "")).lower()
            token_indicators = [
                "runas", "seclogon", "token",
                "duplicate", "impersonate",
                "adjusttokenprivileges",
                "openprocesstoken",
            ]
            for indicator in token_indicators:
                if indicator in name or indicator in cmd:
                    return True
            return False

        # ── 杀软干扰/禁用 ─────────────────────────────────────────
        elif pattern == "antivirus_tamper":
            cmd = str(data_item.get("command_line", "")).lower()
            name = str(data_item.get("name", "")).lower()
            av_tamper_indicators = [
                "sc stop", "sc config", "net stop",
                "taskkill", "stop-service",
                "set-service", "disable",
                "windefend", "mssense", "msmpeng",
                "securityhealthservice",
                "sophos", "mcafee", "symantec",
                "trend", "kaspersky", "eset",
                "avast", "avg", "bitdefender",
                "carbonblack", "crowdstrike",
                "sentinelone", "cylance",
            ]
            cmd_and_name = cmd + " " + name
            for indicator in av_tamper_indicators:
                if indicator in cmd_and_name:
                    return True
            return False

        # ── 防御规避: 日志清除 / 时间戳篡改 ───────────────────────
        elif pattern == "defense_evasion":
            cmd = str(data_item.get("command_line", "")).lower()
            evasion_indicators = [
                "wevtutil cl", "wevtutil clear-log",
                "clearlog", "clear-eventlog",
                "remove-item", "del /f",
                "fsutil behavior set disablelastaccess",
                "fsutil usn deletejournal",
                "auditpol /clear",
                "vssadmin delete shadows",
                "wbadmin delete catalog",
                "bcdedit /set safeboot",
                "bcdedit /set {default} recoveryenabled",
                "timestomp",
                "setfiletime",
            ]
            for indicator in evasion_indicators:
                if indicator in cmd:
                    return True
            # 检查是否在操作 EventLog 或安全日志文件
            log_targets = [
                "security.evtx", "system.evtx",
                "application.evtx", "winevt",
            ]
            for target in log_targets:
                if target in cmd:
                    return True
            return False

        # ── 横向移动 ──────────────────────────────────────────────
        elif pattern == "lateral_movement":
            cmd = str(data_item.get("command_line", "")).lower()
            name = str(data_item.get("name", "")).lower()
            lateral_indicators = [
                "psexec", "psexesvc",
                "wmic /node:", "wmic /user:",
                "schtasks /create /s",
                "schtasks /run /s",
                "winrm", "invoke-command",
                "enter-pssession",
                "new-pssession",
                "copy-item -tosession",
                "net use \\\\", "net use * \\\\",
                "xcopy \\\\", "robocopy \\\\",
                "mapping \\\\",
                "at \\\\",
            ]
            for indicator in lateral_indicators:
                if indicator in cmd:
                    return True
            # WMI 远程执行特征
            wmi_remote = [
                ("wmic.exe" in name or "wmiprvse.exe" in name),
                ("/node:" in cmd),
            ]
            if all(wmi_remote):
                return True
            return False

        # ── 数据外传 ──────────────────────────────────────────────
        elif pattern == "data_exfil":
            cmd = str(data_item.get("command_line", "")).lower()
            exfil_indicators = [
                # 压缩工具
                "7z", "winrar", "rar.exe",
                "makecab", "compact",
                "compress-archive",
                "zip", "gzip", "tar",
                # 上传工具
                "curl", "wget", "ftp",
                "nc ", "netcat",
                "invoke-webrequest",
                "invoke-restmethod",
                "bitsadmin",
                "scp", "rsync",
                "megacmd", "rclone",
            ]
            has_compress = False
            has_upload = False
            compress_keywords = [
                "7z", "winrar", "rar.exe", "makecab", "compact",
                "compress-archive", "zip", "gzip", "tar",
            ]
            upload_keywords = [
                "curl", "wget", "ftp", "nc ", "netcat",
                "invoke-webrequest", "invoke-restmethod",
                "bitsadmin", "scp", "rsync", "megacmd", "rclone",
            ]
            for kw in compress_keywords:
                if kw in cmd:
                    has_compress = True
                    break
            for kw in upload_keywords:
                if kw in cmd:
                    has_upload = True
                    break
            # 同时包含压缩和上传 → 外传
            return has_compress and has_upload

        # ── WebShell 特征 ─────────────────────────────────────────
        elif pattern == "webshell_activity":
            cmd = str(data_item.get("command_line", "")).lower()
            name = str(data_item.get("name", "")).lower()
            webshell_indicators = [
                "eval(", "system(", "exec(",
                "shell_exec", "passthru",
                "proc_open", "popen",
                "base64_decode",
                "assert(",
                "create_function",
                "preg_replace",
                "cmd.exe", "powershell.exe",
                "whoami", "ipconfig",
                "net user", "net localgroup",
            ]
            # 只有在 Web 服务器进程上下文中才报警
            web_servers = [
                "w3wp.exe", "httpd.exe", "apache",
                "nginx", "node.exe", "java",
                "tomcat", "php-cgi", "php",
            ]
            is_web_process = any(ws in name for ws in web_servers)
            if not is_web_process:
                return False
            match_count = 0
            for indicator in webshell_indicators:
                if indicator in cmd:
                    match_count += 1
            return match_count >= 2

        # ── 勒索软件行为 ──────────────────────────────────────────
        elif pattern == "ransomware_behavior":
            cmd = str(data_item.get("command_line", "")).lower()
            name = str(data_item.get("name", "")).lower()
            # 删除卷影副本
            shadow_del = any(k in cmd for k in [
                "vssadmin delete shadows",
                "wmic shadowcopy delete",
                "vssadmin resize shadowstorage",
            ])
            # 批量加密 / 重命名
            encrypt_indicators = [
                "cipher /e", "gpg", "openssl enc",
                "rename-item", "ren *",
                ".encrypted", ".lock", ".crypt",
                ".crab", ".zepto", ".cerber",
                ".locky", ".wannacry",
            ]
            has_encrypt = any(k in cmd for k in encrypt_indicators)
            # 禁用恢复选项
            recovery_disable = any(k in cmd for k in [
                "bcdedit /set {default} recoveryenabled no",
                "bcdedit /set {default} bootstatuspolicy ignoreallfailures",
                "wbadmin delete systemstatebackup",
            ])
            return shadow_del or (has_encrypt and recovery_disable) or has_encrypt

        # ── WMI 持久化 ────────────────────────────────────────────
        elif pattern == "persistence_wmi":
            cmd = str(data_item.get("command_line", "")).lower()
            name = str(data_item.get("name", "")).lower()
            wmi_persist_indicators = [
                "__eventfilter", "__filtertoconsumerbinding",
                "__eventconsumer", "commandlineeventconsumer",
                "activeScriptEventconsumer",
                "set-wmiinstance",
                "register-wmievent",
                "wmi-event", "wmi permanent",
                "root\\subscription",
            ]
            for indicator in wmi_persist_indicators:
                if indicator in cmd or indicator in name:
                    return True
            return False

        # ── COM 劫持持久化 ────────────────────────────────────────
        elif pattern == "persistence_com_hijack":
            cmd = str(data_item.get("command_line", "")).lower()
            com_hijack_indicators = [
                "hkey_classes_root\\clsid",
                "hkey_current_user\\software\\classes\\clsid",
                "inprocserver32",
                "localserver32",
                "treatas",
                "com hijack", "comhijack",
                "oleview",
                "dcomcnfg",
            ]
            for indicator in com_hijack_indicators:
                if indicator in cmd:
                    return True
            return False

        # ── 系统信息探测 ──────────────────────────────────────────
        elif pattern == "discovery_recon":
            cmd = str(data_item.get("command_line", "")).lower()
            recon_commands: list[str] = [
                "systeminfo", "hostname",
                "whoami", "whoami /priv",
                "whoami /groups", "net user",
                "net localgroup", "net group",
                "net share", "net view",
                "net session", "netstat",
                "ipconfig", "ipconfig /all",
                "arp -a", "route print",
                "nslookup", "tracert",
                "tasklist", "tasklist /v",
                "quser", "qwinsta",
                "query user", "query session",
                "dsquery", "net accounts",
                "net domain", "nltest",
                "gpresult", "set",
                "dir /s", "tree /f",
                "wmic product get",
                "wmic qfe", "wmic os get",
                "wmic service get",
                "wmic share get",
                "get-wmiobject",
                "get-process",
                "get-service",
                "get-hotfix",
            ]
            # 如果命令行匹配到 ≥3 个侦察命令 → 高度可疑
            match_count = sum(1 for rc in recon_commands if rc in cmd)
            return match_count >= 3

        # ── DLL 侧加载 ────────────────────────────────────────────
        elif pattern == "dll_sideload":
            path = str(data_item.get("path", "")).lower()
            name = str(data_item.get("name", "")).lower()
            cmd = str(data_item.get("command_line", "")).lower()
            # DLL 侧加载特征: 应用程序从非标准目录加载 DLL
            dll_sideload_indicators: list[str] = [
                "version.dll", "dwrite.dll", "vcruntime140.dll",
                "propsys.dll", "userenv.dll", "duser.dll",
                "mpr.dll", "cscapi.dll", "dbghelp.dll",
                "winshlext", "dwmapi.dll",
            ]
            # 应用在非系统目录运行且加载了常见侧加载 DLL
            system_dirs = [
                "c:\\windows\\system32",
                "c:\\windows\\syswow64",
            ]
            is_non_system = path and not any(d in path for d in system_dirs)
            if not is_non_system:
                return False
            for dll in dll_sideload_indicators:
                if dll in cmd or dll in path:
                    return True
            return False

        # ── 新增模式: process_chain 进程链攻击路径 ────────────────
        elif pattern == "process_chain":
            return RuleEngine._match_process_chain(data_item, condition, global_context)

        # ── 新增模式: time_cluster 时间聚类异常 ──────────────────
        elif pattern == "time_cluster":
            return RuleEngine._match_time_cluster(data_item, condition, global_context)

        # ── 新增模式: short_lived 短存活 Shell ────────────────────
        elif pattern == "short_lived":
            return RuleEngine._match_short_lived(data_item, condition)

        # ── T1 新增 5 个行为模式 ────────────────────────────────
        elif pattern == "process_name_spoof":
            return RuleEngine._match_process_name_spoof(data_item, condition)

        elif pattern == "suspicious_path":
            return RuleEngine._match_suspicious_path(data_item, condition)

        elif pattern == "hidden_process":
            return RuleEngine._match_hidden_process(data_item, condition)

        elif pattern == "anomalous_net_process":
            return RuleEngine._match_anomalous_net_process(data_item, condition, global_context)

        elif pattern == "zombie_process":
            return RuleEngine._match_zombie_process(data_item, condition, global_context)

        # ── 进程检测加强规则集（P0/P1/P2，T02–T17）─────────────────
        elif pattern == "unsigned_exe":
            return RuleEngine._match_unsigned_exe(data_item, condition)
        elif pattern == "whitelist_derived_chain":
            return RuleEngine._match_whitelist_derived_chain(data_item, condition, global_context)
        elif pattern == "ancestry_chain":
            return RuleEngine._match_ancestry_chain(data_item, condition, global_context)
        elif pattern == "parent_pid_spoof":
            return RuleEngine._match_parent_pid_spoof(data_item, condition, global_context)
        elif pattern == "fileless_residency":
            return RuleEngine._match_fileless_residency(data_item, condition)
        elif pattern == "process_respawn":
            return RuleEngine._match_process_respawn(data_item, condition, global_context)
        elif pattern == "revoked_sig":
            return RuleEngine._match_revoked_sig(data_item, condition)
        elif pattern == "memory_injection":
            return RuleEngine._match_memory_injection(data_item, condition)
        elif pattern == "interpreter_mem_pe":
            return RuleEngine._match_interpreter_mem_pe(data_item, condition)
        elif pattern == "etw_amsi_tamper":
            return RuleEngine._match_etw_amsi_tamper(data_item, condition)
        elif pattern == "cross_session":
            return RuleEngine._match_cross_session(data_item, condition, global_context)
        elif pattern == "injection_window":
            return RuleEngine._match_injection_window(data_item, condition, global_context)
        elif pattern == "vanished_process":
            return RuleEngine._match_vanished_process(data_item, condition, global_context)

        # ── 兼容旧 rule_matcher 行为模式（P0-1 适配层）──────────────
        elif pattern == "child_of_office":
            parent = str(data_item.get("parent_name") or data_item.get("parent_process_name") or "").lower().strip()
            if not parent:
                return False
            return any(x in parent for x in ("winword", "excel", "powerpnt", "outlook", "wordpad"))

        elif pattern == "child_of_browser":
            parent = str(data_item.get("parent_name") or data_item.get("parent_process_name") or "").lower().strip()
            if not parent:
                return False
            return any(x in parent for x in ("chrome", "firefox", "msedge", "iexplore", "opera"))

        elif pattern == "high_value_path":
            path = str(data_item.get("process_path") or data_item.get("path") or "").lower()
            return any(x in path for x in (r"\temp", r"\tmp", r"\downloads", r"\appdata\local\temp"))

        # ── 未知模式 ──────────────────────────────────────────────
        logger.warning("Unknown behavior pattern: %s", pattern)
        return False

    # ── 进程链攻击路径检测 ──────────────────────────────────────────────

    @staticmethod
    def _match_process_chain(data_item: dict, condition: dict, global_context: Optional[dict] = None) -> bool:
        """检测 ≥min_chain_length 级可疑进程链路（攻击路径）.

        从 global_context 获取 process_map（pid→process dict），从当前进程回溯父链，
        检测链路中 ≥min_chain_length 个进程属于 suspicious_patterns。
        需要同时在链路起点有 suspicious_parent 和链路中间有 suspicious_child。

        Args:
            data_item: 当前进程数据项.
            condition: 规则条件，包含 min_chain_length, suspicious_parent_patterns, suspicious_child_patterns.
            global_context: 全局上下文，需包含 process_map（pid→process dict）.

        Returns:
            是否检测到进程链攻击.
        """
        if not global_context:
            return False

        process_map: dict = global_context.get("process_map", {})
        if not process_map:
            return False

        min_chain_length: int = condition.get("min_chain_length", 3)
        suspicious_parent_patterns: list = condition.get("suspicious_parent_patterns", [])
        suspicious_child_patterns: list = condition.get("suspicious_child_patterns", [])

        # 从当前进程回溯父链
        chain: list[dict] = []
        current_pid = data_item.get("pid")

        # 向上回溯父进程链（最多 10 层防止无限循环）
        max_depth = 10
        visited_pids: set = set()
        pid = current_pid
        while pid is not None and pid not in visited_pids and max_depth > 0:
            proc = process_map.get(pid)
            if proc is None:
                break
            visited_pids.add(pid)
            chain.append(proc)
            pid = proc.get("ppid")
            max_depth -= 1

        # 链路长度不足
        if len(chain) < min_chain_length:
            return False

        # 检查链路中可疑进程数量
        suspicious_count = 0
        has_suspicious_parent = False
        has_suspicious_child = False

        for proc in chain:
            proc_name = str(proc.get("name", "")).lower()
            if any(p.lower() in proc_name for p in suspicious_parent_patterns):
                has_suspicious_parent = True
                suspicious_count += 1
            if any(p.lower() in proc_name for p in suspicious_child_patterns):
                has_suspicious_child = True
                suspicious_count += 1

        # 需要同时有可疑父进程和可疑子进程
        if not has_suspicious_parent or not has_suspicious_child:
            return False

        if suspicious_count >= min_chain_length:
            # 记录攻击路径到 data_item 中，用于后续 _apply_accumulated_scoring
            attack_path_names = [str(p.get("name", "")) for p in chain]
            data_item["_attack_path"] = " → ".join(attack_path_names)
            return True

        return False

    # ── 时间聚类异常检测 ──────────────────────────────────────────────

    @staticmethod
    def _match_time_cluster(data_item: dict, condition: dict, global_context: Optional[dict] = None) -> bool:
        """同一时间窗口内 ≥min_count 个进程启动触发告警.

        从 global_context 获取 all_items（所有进程列表），对 data_item 的 start_time，
        检查同一时间窗口（window_minutes）内有 ≥min_count 个进程启动。

        Args:
            data_item: 当前进程数据项.
            condition: 规则条件，包含 window_minutes, min_count.
            global_context: 全局上下文，需包含 all_items（所有进程列表）.

        Returns:
            是否检测到时间聚类异常.
        """
        if not global_context:
            return False

        all_items: list = global_context.get("all_items", [])
        if not all_items:
            return False

        window_minutes: int = condition.get("window_minutes", 5)
        min_count: int = condition.get("min_count", 5)

        current_start_time = data_item.get("start_time", "")
        if not current_start_time:
            return False

        # 解析当前进程的 start_time
        try:
            from datetime import datetime, timedelta
            # 支持多种常见时间格式
            time_formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y/%m/%d %H:%M:%S",
            ]
            current_time = None
            for fmt in time_formats:
                try:
                    current_time = datetime.strptime(str(current_start_time).split("+")[0].split("Z")[0], fmt)
                    break
                except ValueError:
                    continue
            if current_time is None:
                return False

            window_start = current_time - timedelta(minutes=window_minutes)
            window_end = current_time + timedelta(minutes=window_minutes)

            # T-P2-4: 优先使用预排序列表 + 二分计数，将 O(n²) 降至 O(n log n)
            dts = global_context.get("_tc_dts")
            if dts:
                import bisect

                lo = bisect.bisect_left(dts, window_start)
                hi = bisect.bisect_right(dts, window_end)
                return (hi - lo) >= min_count

            # 回退：未预排序时线性扫描（保持旧逻辑兼容）
            count_in_window = 0
            for item in all_items:
                if not isinstance(item, dict):
                    continue
                item_start_time = item.get("start_time", "")
                if not item_start_time:
                    continue
                item_time = None
                for fmt in time_formats:
                    try:
                        item_time = datetime.strptime(str(item_start_time).split("+")[0].split("Z")[0], fmt)
                        break
                    except ValueError:
                        continue
                if item_time and window_start <= item_time <= window_end:
                    count_in_window += 1

            return count_in_window >= min_count
        except Exception as exc:
            logger.warning("Error in time_cluster detection: %s", exc)
            return False

    # ── 短存活 Shell 进程检测 ──────────────────────────────────────────

    @staticmethod
    def _match_short_lived(data_item: dict, condition: dict) -> bool:
        """powershell/cmd 进程存活时间 < max_alive_seconds 触发告警.

        检查 data_item.name 是否在 target_processes 中，
        如果 threads=0 或进程存活时间 < max_alive_seconds，判断为短存活进程。

        Args:
            data_item: 当前进程数据项.
            condition: 规则条件，包含 target_processes, max_alive_seconds.

        Returns:
            是否检测到短存活 Shell.
        """
        target_processes: list = condition.get("target_processes", [])
        max_alive_seconds: int = condition.get("max_alive_seconds", 30)

        proc_name = str(data_item.get("name", "")).lower()
        # 检查是否为目标进程
        is_target = any(t.lower() == proc_name for t in target_processes)
        if not is_target:
            return False

        # 检查 threads=0（进程已退出）
        threads = data_item.get("threads", 0)
        if threads == 0:
            return True

        # 检查存活时间 < max_alive_seconds
        start_time_str = data_item.get("start_time", "")
        if start_time_str:
            try:
                from datetime import datetime
                time_formats = [
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S.%f",
                    "%Y-%m-%dT%H:%M:%S.%f",
                    "%Y/%m/%d %H:%M:%S",
                ]
                start_time = None
                for fmt in time_formats:
                    try:
                        start_time = datetime.strptime(str(start_time_str).split("+")[0].split("Z")[0], fmt)
                        break
                    except ValueError:
                        continue
                if start_time:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed < max_alive_seconds and threads <= 1:
                        return True
            except Exception:
                pass

        return False

    # ── 进程名伪装检测（process_name_spoof）─────────────────────────────

    @staticmethod
    def _match_process_name_spoof(data_item: dict, condition: dict) -> bool:
        """进程名伪装检测：双扩展名 / 大小写混淆 / 相似名 / Unicode 同形.

        任一命中即报（三重判定，阈值严格，避免正常短名误报）：
          1. 双扩展名：可执行叠加可执行（evil.exe.exe）或良性文档叠加可执行（evil.jpg.exe）；
          2. 大小写混淆：归一化名命中系统进程白名单但原始名含大写（如 PowerShell.exe）；
          3. 相似名：与白名单编辑距离 == 1（如 svch0st → svchost、cxmd → cmd）；
          4. Unicode 同形：含非 ASCII 且 NFKC/同形归一后命中白名单（如 ｓｖｃｈｏｓｔ）。

        Args:
            data_item: 进程数据项（读 name）。
            condition: 规则条件。

        Returns:
            是否命中进程名伪装。
        """
        name = str(data_item.get("name", ""))
        if not name:
            return False
        base_norm = _norm_proc_name(name)

        # 1) 双扩展名
        if _SPOOF_DOUBLE_EXEC_RE.search(name) or _SPOOF_BENIGN_EXE_RE.search(name):
            return True

        # 2) 大小写混淆：归一化名命中白名单，但原始名非全小写
        if base_norm in _SYSTEM_PROC_WHITELIST and name.strip() != name.strip().lower():
            return True

        # 3) 相似名（编辑距离 == 1）
        for w in _SYSTEM_PROC_WHITELIST:
            if _levenshtein(base_norm, w) == 1:
                return True

        # 4) Unicode 同形：含非 ASCII 字符且归一后命中白名单
        if any(ord(ch) > 127 for ch in name):
            folded = unicodedata.normalize("NFKC", name)
            folded = _normalize_confusable(folded)
            if _norm_proc_name(folded) in _SYSTEM_PROC_WHITELIST:
                return True

        return False

    # ── 可疑进程路径检测（suspicious_path）──────────────────────────────

    @staticmethod
    def _match_suspicious_path(data_item: dict, condition: dict) -> bool:
        """可疑进程路径检测：临时/下载/AppData/伪装 system32/ADS/UNC.

        触发条件（任一，且不在白名单）：
          - 用户可写/临时目录（temp/tmp/downloads/appdata/programdata/desktop/public/users）；
          - 伪装 system32：含 system32 但前缀非 c:\\windows\\system32；
          - 用户目录下的 exe（非 AppData\\Local\\Programs）；
          - ADS 备用数据流（basename 含冒号）或异常 UNC（以 \\\\ 开头）。
        白名单（误报控制，附录B）：Program Files / Windows\\system32 / Windows\\SysWOW64 /
        ProgramData 下 *.install 安装器目录。

        Args:
            data_item: 进程数据项（读 path）。
            condition: 规则条件。

        Returns:
            是否命中可疑路径。
        """
        path = str(data_item.get("path", "")).lower()
        if not path:
            return False

        # 白名单：合法系统/程序目录
        for w in _SUSPICIOUS_PATH_WHITELIST:
            if w in path:
                return False
        # ProgramData 下 *.install 安装器目录白名单（避免合法更新程序误报）
        if "programdata" in path:
            tail = path.split("programdata", 1)[1]
            if ".install" in tail:
                return False
        # AppData\Local\Programs 下为合法用户安装程序（Teams/Discord/Slack/Python
        # launcher 等），豁免误报（§3.2：用户目录 exe 且非该目录才命中）。
        # 必须在下方标记检查之前排除，否则 "appdata\local" 标记会先 return True。
        if "appdata\\local\\programs" in path:
            return False

        # 1) 用户可写/临时目录
        if any(m in path for m in _SUSPICIOUS_PATH_MARKERS):
            return True
        # 2) 伪装 system32（盘符仿冒 / system32.exe 伪装）
        if "system32" in path and not re.search(r"c:\\windows\\system32(\\|$)", path):
            return True
        # 3) 用户目录下的 exe（非 AppData\\Local\\Programs）
        if "users\\" in path and "appdata\\local\\programs" not in path:
            return True
        # 4) ADS 备用数据流 或 异常 UNC
        if path.startswith("\\\\"):
            return True
        if re.search(r"\\[^\\/:]*:[^\\/:]+", path):
            return True
        return False

    # ── 隐蔽/仿冒服务进程检测（hidden_process）──────────────────────────

    @staticmethod
    def _match_hidden_process(data_item: dict, condition: dict) -> bool:
        """隐蔽/仿冒服务进程检测.

        退化判定（决策5，数据无 window_title/session 时）：
          进程名与系统服务同名但路径不在 system32/syswow64（仿冒服务进程，如 svchost.exe 在 C:\\Temp\\）。
        增强判定（数据含 window_title/session 时）：
          交互式进程（powershell/cmd/rundll32/wscript/cscript）无窗口标题且 session>0 → 疑似隐藏。

        Args:
            data_item: 进程数据项（读 name/path/window_title/session）。
            condition: 规则条件。

        Returns:
            是否命中隐蔽/仿冒服务进程。
        """
        name = str(data_item.get("name", ""))
        base = _norm_proc_name(name)
        path = str(data_item.get("path", "")).lower()
        service_names = _SYSTEM_PROC_WHITELIST

        # 退化判定：同名不同路径（仿冒系统服务）
        if base in service_names and path:
            if "windows\\system32" not in path and "windows\\syswow64" not in path:
                return True

        # 增强判定：无窗口隐藏（需数据含 window_title/session 字段）
        if "window_title" in data_item and "session" in data_item:
            wt = data_item.get("window_title")
            session = data_item.get("session", 0)
            interactive = {"powershell", "cmd", "rundll32", "wscript", "cscript"}
            try:
                session_int = int(session)
            except (ValueError, TypeError):
                session_int = 0
            if wt == "" and session_int > 0 and base in interactive:
                return True

        return False

    # ── 异常网络连接进程检测（anomalous_net_process）────────────────────

    @staticmethod
    def _match_anomalous_net_process(data_item: dict, condition: dict,
                                     global_context: Optional[dict] = None) -> bool:
        """异常网络连接进程检测（跨维度）.

        从 data_item.connections（detect_processes 已补全）或 global_context["connections"]
        取该 pid 的外连，触发条件（任一）：
          - 脚本解释器/无签名进程发起非业务端口外连；
          - 进程连接常见 C2/代理端口（4444/8443/1337/31337/6667/9999/1080/5900）。

        Args:
            data_item: 进程数据项（读 name/path/pid/connections）。
            condition: 规则条件。
            global_context: 全局上下文，需含 connections（T3 补充）。

        Returns:
            是否命中异常网络连接进程。
        """
        pid = data_item.get("pid")
        # 优先 data_item.connections，回退 global_context["connections"]（按 pid 过滤）
        conns = data_item.get("connections")
        if not isinstance(conns, list):
            conns = []
        if not conns and global_context:
            all_conns = global_context.get("connections") or []
            if isinstance(all_conns, list):
                conns = [c for c in all_conns if c.get("pid") == pid]
        if not conns:
            return False

        name = _norm_proc_name(str(data_item.get("name", "")))
        path = str(data_item.get("path", "")).lower()
        # 非系统目录：排除 system32/syswow64 与 Program Files（含 x86）。
        # 避免 C:\Program Files\SomeApp\updater.exe 连非业务端口被误报（附录B 误报控制）。
        non_system = (
            bool(path)
            and "windows\\system32" not in path
            and "windows\\syswow64" not in path
            and "program files" not in path
        )

        for c in conns:
            remote_port = c.get("remote_port", c.get("dst_port", 0))
            try:
                remote_port = int(remote_port)
            except (ValueError, TypeError):
                remote_port = 0
            # 脚本解释器/无签名进程的非业务端口外连
            if name in _ANOMALOUS_NET_INTERPRETERS and remote_port not in _BUSINESS_PORTS:
                return True
            if non_system and remote_port not in _BUSINESS_PORTS:
                return True
            # 常见 C2/代理端口
            if remote_port in _C2_PORTS:
                return True
        return False

    # ── 疑似僵尸/残留进程检测（zombie_process，启发式）──────────────────

    @staticmethod
    def _match_zombie_process(data_item: dict, condition: dict,
                              global_context: Optional[dict] = None) -> bool:
        """疑似僵尸/残留进程检测（数据受限启发式，需人工确认）.

        Windows 离线取证通常无 zombie 状态字段，本启发式（降级为"疑似"）：
          进程线程数为 0（残留句柄）或完全孤立（无任何外连），且启动时间距今
          超过阈值（默认 7 天）→ 疑似僵尸/残留进程。命中仅作"疑似"，severity 由
          规则定为 high 且 reason 明示"待人工确认"。

        Args:
            data_item: 进程数据项（读 pid/threads/start_time/connections）。
            condition: 规则条件（threshold_days，默认 7）。
            global_context: 全局上下文（预留，当前未使用）。

        Returns:
            是否疑似僵尸/残留进程。
        """
        threshold_days = int(condition.get("threshold_days", 7) or 7)
        threads = data_item.get("threads", 1)
        start_time = data_item.get("start_time", "")
        ts = _parse_datetime(start_time)
        if ts is None:
            return False
        try:
            old = (datetime.now() - ts) > timedelta(days=threshold_days)
        except Exception:
            return False
        if not old:
            return False
        # 线程数为 0（残留句柄）或完全孤立（无外连）→ 疑似残留
        conns = data_item.get("connections")
        conn_count = len(conns) if isinstance(conns, list) else 0
        return threads == 0 or conn_count == 0

    # ── 无签名 exe（unsigned_exe，T05）────────────────────────────────
    @staticmethod
    def _match_unsigned_exe(data_item: dict, condition: dict) -> bool:
        """无数字签名的非系统目录 exe（JOIN file_hashes 注入 exe_is_signed/exe_signer）.

        触发：exe_is_signed 为 0/空/缺失（或 exe_signer 空而标记为已签名），
        且进程路径不在系统目录（视为无签名的可疑 exe）。
        """
        path = str(data_item.get("path", "")).lower()
        if not path:
            # 无路径进程（fileless）由 fileless_residency 评估，此处不误报
            return False
        system_dirs = [
            "c:\\windows\\system32",
            "c:\\windows\\syswow64",
            "c:\\program files",
            "c:\\program files (x86)",
            "/usr/bin",
            "/usr/sbin",
            "/bin",
            "/sbin",
        ]
        if any(d in path for d in system_dirs):
            return False
        exe_is_signed = data_item.get("exe_is_signed")
        exe_signer = data_item.get("exe_signer")
        if exe_is_signed in (0, None, "", False):
            return True
        # 标记为已签名但签名为空 → 异常，按无签名处理
        if exe_is_signed == 1 and exe_signer in (None, ""):
            return True
        return False

    # ── 白名单派生链（whitelist_derived_chain，T04 根因修复）────────────
    @staticmethod
    def _match_whitelist_derived_chain(data_item: dict, condition: dict,
                                       global_context: Optional[dict] = None) -> bool:
        """白名单进程派生的可疑子链.

        触发：当前进程的父进程被标记为 whitelisted（命中白名单、保留建树），
        且当前进程为脚本解释器/LOLBin 或其命令行含可疑解码/下载参数。
        """
        if not global_context:
            return False
        process_map = global_context.get("process_map", {})
        ppid = data_item.get("ppid")
        if ppid is None:
            return False
        parent = process_map.get(ppid)
        if not parent or not parent.get("whitelisted"):
            return False
        name = _norm_proc_name(str(data_item.get("name", "")))
        derived_children = {
            "powershell", "cmd", "wscript", "cscript", "rundll32", "mshta",
            "certutil", "bitsadmin", "wmic", "regsvr32", "javaw", "python",
            "perl", "ruby", "pwsh", "iexplore",
        }
        if name in derived_children:
            return True
        cmd = str(data_item.get("command_line", "")).lower()
        if any(k in cmd for k in (
            "-enc", "-encodedcommand", "-decode", "-decodehex",
            "-urlcache", "iex", "downloadstring", "frombase64",
        )):
            return True
        return False

    # ── 祖辈链异常（ancestry_chain，T07）──────────────────────────────
    @staticmethod
    def _match_ancestry_chain(data_item: dict, condition: dict,
                              global_context: Optional[dict] = None) -> bool:
        """祖辈（祖父）链异常.

        触发：本进程为脚本解释器/LOLBin，且其多级祖先链（ancestor_map）中存在
        可疑系统服务/异常服务祖父。沿 global_context["ancestor_map"] 回溯。
        """
        if not global_context:
            return False
        process_map = global_context.get("process_map", {})
        ancestor_map = global_context.get("ancestor_map", {})
        suspicious_grandparents = condition.get("suspicious_grandparents") or _DEFAULT_SUSPICIOUS_GRANDPARENTS
        suspicious_grandparents = {_norm_proc_name(p) for p in suspicious_grandparents}
        suspicious_children = condition.get("suspicious_children") or _DEFAULT_SUSPICIOUS_CHILDREN
        suspicious_children = {_norm_proc_name(c) for c in suspicious_children}

        name = _norm_proc_name(str(data_item.get("name", "")))
        if name not in suspicious_children:
            return False
        anc_pids = ancestor_map.get(data_item.get("pid"))
        if not anc_pids:
            return False
        for apid in anc_pids:
            aproc = process_map.get(apid)
            if not aproc:
                continue
            aname = _norm_proc_name(str(aproc.get("name", "")))
            if aname in suspicious_grandparents:
                return True
        return False

    # ── 伪造/不可能父 PID（parent_pid_spoof，T10 字段级）────────────────
    @staticmethod
    def _match_parent_pid_spoof(data_item: dict, condition: dict,
                                global_context: Optional[dict] = None) -> bool:
        """伪造/不可能父 PID（字段级，升级原 parent_pid_spoofing 命令行规则）.

        触发：ppid == pid（自指）或 父子互指环（父的 ppid 指向子本身）。
        """
        pid = data_item.get("pid")
        ppid = data_item.get("ppid")
        if pid is None or ppid is None:
            return False
        if ppid == pid:
            return True
        process_map = (global_context or {}).get("process_map", {})
        parent = process_map.get(ppid)
        if parent is not None and parent.get("ppid") == pid:
            # 互指父子环：不可能
            return True
        return False

    # ── fileless 内存驻留（fileless_residency，T11 快照版）──────────────
    @staticmethod
    def _match_fileless_residency(data_item: dict, condition: dict) -> bool:
        """fileless 内存驻留（快照可部分实现）.

        触发：path 为空 / UNC / 内存伪路径，但存在活跃连接或线程
        （无磁盘落地的内存驻留进程，基于现有 path/connections 字段）。
        """
        path = str(data_item.get("path", "")).strip()
        if not path:
            is_fileless = True
        else:
            low = path.lower()
            is_fileless = (
                low.startswith("\\\\")
                or "memory" in low
                or "memfd:" in low
                or low.startswith("/proc/")
                or low.startswith("\\??\\")
                or ("lsass" in low and "mem" in low)
            )
        if not is_fileless:
            return False
        connections = data_item.get("connections") or []
        conn_count = len(connections) if isinstance(connections, list) else 0
        threads = data_item.get("threads", 0) or 0
        return conn_count > 0 or threads > 0

    # ── 短时间重复进程重生（process_respawn，T12 快照近似）──────────────
    @staticmethod
    def _match_process_respawn(data_item: dict, condition: dict,
                               global_context: Optional[dict] = None) -> bool:
        """短时间窗口内同 path/command_line 重复 ≥K 次（快照近似爆发）.

        退化：精确计数依赖事件流；快照下按同指纹（path+command_line）在 all_items 中
        出现次数近似（若均提供可解析 start_time，则仅统计窗口内的重复）。

        已知系统进程（System/Registry/svchost 等）正常多实例，直接排除。
        """
        proc_name = str(data_item.get("name", "")).lower()
        if proc_name in _SYSTEM_PROCESS_NAMES:
            return False
        if not global_context:
            return False
        all_items = global_context.get("all_items")
        if not isinstance(all_items, list) or not all_items:
            return False
        min_count = int(condition.get("min_count", 3) or 3)
        window_min = int(condition.get("window_minutes", 60) or 60)
        fp = (str(data_item.get("path", "")) + "|" + str(data_item.get("command_line", ""))).lower()
        base_ts = data_item.get("start_time", "")
        count = 0
        for it in all_items:
            if not isinstance(it, dict):
                continue
            it_fp = (str(it.get("path", "")) + "|" + str(it.get("command_line", ""))).lower()
            if it_fp != fp:
                continue
            it_ts = it.get("start_time", "")
            if base_ts and it_ts:
                bt = _parse_datetime(base_ts)
                it_t = _parse_datetime(it_ts)
                if bt and it_t:
                    if abs((bt - it_t).total_seconds()) / 60.0 > window_min:
                        continue
            count += 1
        return count >= min_count

    # ── 签名被吊销/过期（revoked_sig，T17 离线缓存）───────────────────
    @staticmethod
    def _match_revoked_sig(data_item: dict, condition: dict) -> bool:
        """签名被吊销/过期（离线 CRL/OCSP 缓存）.

        触发：exe_signer 命中吊销库（revoked_ca.json）。吊销库为空时降级返回 False。
        """
        signer = data_item.get("exe_signer")
        if not signer:
            return False
        revoked = _load_revoked_signers()
        if not revoked:
            return False
        return str(signer).lower() in revoked

    # ── 无文件内存注入（memory_injection，T16 需 memory_sections）──────
    @staticmethod
    def _match_memory_injection(data_item: dict, condition: dict) -> bool:
        """无文件内存注入（reflective/hollowing/远线程）.

        触发：进程 memory_sections 含「内存中 PE 镜像 / 非映像基址注入痕迹」。
        缺 memory_sections 字段时优雅降级返回 False。
        """
        sections = data_item.get("memory_sections")
        if not isinstance(sections, list) or not sections:
            return False
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            if sec.get("injection") or sec.get("pe_in_memory") or sec.get("reflective"):
                return True
            stype = str(sec.get("type", "")).lower()
            if "mem_image" in stype or "memory_pe" in stype or stype == "pe":
                return True
            if sec.get("base_address") and sec.get("is_non_image"):
                return True
        return False

    # ── 脚本解释器内存加载异常 PE（interpreter_mem_pe，T16）────────────
    @staticmethod
    def _match_interpreter_mem_pe(data_item: dict, condition: dict) -> bool:
        """脚本解释器内存加载异常 PE（需 memory_sections / ETW ImageLoad）.

        触发：进程为脚本解释器（powershell/python 等）且 memory_sections 含内存 PE 痕迹。
        缺内存采集时优雅降级返回 False。
        """
        name = _norm_proc_name(str(data_item.get("name", "")))
        interpreters = {"powershell", "pwsh", "python", "python3", "perl", "ruby", "node", "java"}
        if name not in interpreters:
            return False
        sections = data_item.get("memory_sections")
        if not isinstance(sections, list) or not sections:
            return False
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            if sec.get("injection") or sec.get("pe_in_memory") or sec.get("reflective"):
                return True
            stype = str(sec.get("type", "")).lower()
            if "mem_image" in stype or "memory_pe" in stype or stype == "pe":
                return True
        return False

    # ── ETW/AMSI 旁路（etw_amsi_tamper，T16 事件级）────────────────────
    @staticmethod
    def _match_etw_amsi_tamper(data_item: dict, condition: dict) -> bool:
        """ETW/AMSI 旁路（事件级，需 ETW 事件流）.

        触发：进程携带 etw_events（由 process_event_consumer 归一化注入），
        且含 ETW provider 禁用 / AMSI 内存修补事件。缺事件流时优雅降级返回 False。
        """
        events = data_item.get("etw_events")
        if not isinstance(events, list) or not events:
            return False
        for ev in events:
            if not isinstance(ev, dict):
                continue
            etype = str(ev.get("event_type", "")).lower()
            detail = str(ev.get("detail", "")).lower()
            if "etw" in etype and ("disable" in detail or "stop" in detail or "unregister" in detail):
                return True
            if "amsi" in etype or "amsi" in detail:
                if "patch" in detail or "tamper" in detail or "bypass" in detail:
                    return True
        return False

    # ── 跨会话/跨用户父子（cross_session，T16 需 session）──────────────
    @staticmethod
    def _match_cross_session(data_item: dict, condition: dict,
                             global_context: Optional[dict] = None) -> bool:
        """跨会话/跨用户父子（需 session 字段）.

        触发：父 session==0（系统会话）但子为交互会话（session>0），
        或父子 user 不同。缺 session 字段时优雅降级返回 False。
        """
        if "session" not in data_item:
            return False
        try:
            session = int(data_item.get("session"))
        except (ValueError, TypeError):
            return False
        if not global_context:
            return False
        process_map = global_context.get("process_map", {})
        ppid = data_item.get("ppid")
        parent = process_map.get(ppid) if ppid is not None else None
        if parent is None or "session" not in parent:
            return False
        try:
            parent_session = int(parent.get("session"))
        except (ValueError, TypeError):
            return False
        if parent_session == 0 and session > 0:
            return True
        parent_user = parent.get("user")
        child_user = data_item.get("user")
        if parent_user and child_user and parent_user != child_user:
            return True
        return False

    # ── 注入行为窗口异常（injection_window，T16 需事件流）──────────────
    @staticmethod
    def _match_injection_window(data_item: dict, condition: dict,
                                global_context: Optional[dict] = None) -> bool:
        """注入行为窗口异常（需事件流：启动后极短窗口内建远线程）.

        触发：进程携带 remote_thread_events，且首条远线程事件距 start_time < max_alive_seconds。
        缺事件流时优雅降级返回 False。
        """
        events = data_item.get("remote_thread_events")
        if not isinstance(events, list) or not events:
            return False
        start_time = data_item.get("start_time", "")
        ts = _parse_datetime(start_time)
        if ts is None:
            return False
        from datetime import datetime
        elapsed = (datetime.now() - ts).total_seconds()
        if elapsed < 0 or elapsed > 3600:
            return False
        max_alive = int(condition.get("max_alive_seconds", 2) or 2)
        for ev in events:
            if not isinstance(ev, dict):
                continue
            ets = _parse_datetime(ev.get("timestamp", ""))
            if ets is None:
                continue
            if 0 <= (ets - ts).total_seconds() <= max_alive:
                return True
        return False

    # ── 快照间消失进程（vanished_process，T16 需 process_events）────────
    @staticmethod
    def _match_vanished_process(data_item: dict, condition: dict,
                                global_context: Optional[dict] = None) -> bool:
        """快照间出现又消失的进程（需 process_events 表）.

        触发：本进程仅见于事件流（seen_in_events）但不在完整快照（seen_in_snapshot 缺失）。
        由 process_event_consumer 归一化时标注。缺事件标注时优雅降级返回 False。
        """
        if data_item.get("seen_in_events") and not data_item.get("seen_in_snapshot"):
            return True
        return False

    # ── 攻击链关联检测（主机级）─────────────────────────────────────────

    @staticmethod
    def _build_host_events(global_context: Optional[dict]) -> list:
        """按 host_id 聚合各维度取证数据为统一时间线事件列表.

        每个事件结构::

            {"dimension": "process"|"connection"|"registry"|"persistence"|"timeline"|"ioc",
             "timestamp": Optional[datetime],   # 无可信时间戳的维度为 None（退化为「仅顺序」）
             "data": dict}                       # 原始记录字段，供 step.match 直接命中

        时间戳来源（最高优先级优先）：
          - timeline    → timestamp
          - registry    → last_write_time（退化到 collected_at）
          - process/connection/persistence/ioc → 无可靠时间戳，置 None（仅顺序匹配）

        返回前按 timestamp 升序排序；无时间戳事件统一置于末尾，保证跨维度顺序贪心可用。

        Args:
            global_context: 全局上下文，须含 host_id。

        Returns:
            统一事件列表（已排序）。任何 DB 异常均降级为空列表。
        """
        if not global_context:
            return []
        host_id = global_context.get("host_id")
        if host_id is None:
            return []

        from datetime import datetime  # 供 _sort_key 兜底排序（datetime.min）使用

        def _parse_ts(value) -> Optional["__import__('datetime').datetime"]:
            from datetime import datetime
            if not value:
                return None
            s = str(value).split("+")[0].split("Z")[0]
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y/%m/%d %H:%M:%S",
            ):
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue
            return None

        events: list = []
        try:
            from app.models.analysis import (
                AbnormalProcess, SuspiciousConnection, PersistenceItem,
                TimelineEvent, IocHit, RegistryKey,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("跳过攻击链事件聚合（analysis 模型不可用）: %s", exc)
            return []

        try:
            # 进程（无可靠时间戳）
            for r in AbnormalProcess.list_by_host(host_id):
                events.append({"dimension": "process", "timestamp": None, "data": dict(r)})
            # 可疑外连（无可靠时间戳；兼容 network_connections 的 remote_addr 别名）
            for r in SuspiciousConnection.list_by_host(host_id):
                d = dict(r)
                if "remote_address" not in d and d.get("remote_addr") is not None:
                    d["remote_address"] = d["remote_addr"]
                events.append({"dimension": "connection", "timestamp": None, "data": d})
            # 持久化痕迹（无可靠时间戳）
            for r in PersistenceItem.list_by_host(host_id):
                events.append({"dimension": "persistence", "timestamp": None, "data": dict(r)})
            # IOC 命中（无可靠时间戳）
            for r in IocHit.list_by_host(host_id):
                events.append({"dimension": "ioc", "timestamp": None, "data": dict(r)})
            # 注册表（last_write_time 退化到 collected_at）
            for r in RegistryKey.list_by_host(host_id):
                d = dict(r)
                ts = _parse_ts(d.get("last_write_time")) or _parse_ts(d.get("collected_at"))
                events.append({"dimension": "registry", "timestamp": ts, "data": d})
            # 时间线（timestamp 可信）
            for r in TimelineEvent.list_by_host(host_id):
                events.append({
                    "dimension": "timeline",
                    "timestamp": _parse_ts(r.get("timestamp")),
                    "data": dict(r),
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug("攻击链事件聚合部分失败，降级为空: %s", exc)
            return []

        # 排序：有时间戳在前（升序），无时间戳（None）置于末尾
        def _sort_key(e):
            ts = e.get("timestamp")
            return (ts is None, ts if ts is not None else datetime.min)

        events.sort(key=_sort_key)
        return events

    @staticmethod
    def _match_attack_chain_step(step: dict, event_data: dict,
                                 global_context: Optional[dict] = None) -> bool:
        """对单条统一事件应用攻击链某步的 match 条件.

        step.match.type ∈ {regex, list, threshold, behavior, exists, composite}，
        直接复用引擎既有 _match_* 实现，保证语义一致。

        Args:
            step: ordered_steps 中的单步（含 dimension + match）。
            event_data: 统一事件的 data 字典。
            global_context: 全局上下文（透传给 composite/behavior/threshold）。

        Returns:
            该步是否命中此事件。
        """
        match = step.get("match", {})
        if not isinstance(match, dict):
            return False
        mtype = match.get("type", "")
        if mtype == "regex":
            return RuleEngine._match_regex(event_data, match)
        elif mtype == "list":
            return RuleEngine._match_list(event_data, match, global_context=global_context)
        elif mtype == "threshold":
            return RuleEngine._match_threshold(event_data, match)
        elif mtype == "exists":
            return RuleEngine._match_exists(event_data, match)
        elif mtype == "composite":
            return RuleEngine._match_composite(event_data, match, global_context=global_context)
        elif mtype == "behavior":
            return RuleEngine._match_behavior(event_data, match, global_context=global_context)
        logger.warning("Unknown attack_chain step match.type: %s", mtype)
        return False

    @staticmethod
    def _match_attack_chain(rule: dict, global_context: Optional[dict] = None,
                            host_events: Optional[list] = None) -> Optional[dict]:
        """主机级攻击链贪心顺序匹配 + 时间窗判定.

        算法：
          1. 按 ordered_steps 顺序，在「按时间升序」的统一事件列表中贪心选取：
             每步须找到 dimension 匹配且 _match_attack_chain_step 命中、且位于上一步
             索引之后（保证顺序）的首个事件。
          2. 所有步骤命中后，对「具有时间戳的步骤事件」计算首末跨度 span；
             若 span > window_minutes，则视为超窗不命中（无时间戳步骤不参与时间约束）。

        Args:
            rule: attack_chain 规则字典（condition 含 ordered_steps / window_minutes）。
            global_context: 全局上下文（用于下钻构建事件、透传 IOC 等）。
            host_events: 可选预构建事件列表（单元测试可直接注入，跳过 DB 下钻）。

        Returns:
            命中返回 {"steps": [...明细...], "reason": str}；否则返回 None。
        """
        if not global_context:
            global_context = {}
        condition = rule.get("condition", {})
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except json.JSONDecodeError:
                return None
        steps = condition.get("ordered_steps") or []
        if not steps:
            return None
        window_minutes = int(condition.get("window_minutes", 60) or 60)
        # 防御：window_minutes 上限 1440（与设计校验一致）
        window_minutes = max(1, min(window_minutes, 1440))

        if host_events is None:
            host_events = RuleEngine._build_host_events(global_context)
        if not host_events:
            return None

        matched_times: list = []
        matched_steps: list = []
        pointer = 0
        for idx, step in enumerate(steps):
            dim = step.get("dimension")
            found = False
            for j in range(pointer, len(host_events)):
                ev = host_events[j]
                if ev.get("dimension") != dim:
                    continue
                if not RuleEngine._match_attack_chain_step(step, ev.get("data", {}), global_context):
                    continue
                # 命中：记录
                ts = ev.get("timestamp")
                if ts is not None:
                    matched_times.append(ts)
                matched_steps.append({
                    "step": idx + 1,
                    "dimension": dim,
                    "match": step.get("match"),
                    "summary": RuleEngine._summarize_event(ev),
                })
                pointer = j + 1
                found = True
                break
            if not found:
                return None

        # 时间窗判定：仅在「有 ≥1 个带时间戳步骤」时生效
        if len(matched_times) >= 2:
            from datetime import timedelta
            span = (max(matched_times) - min(matched_times)).total_seconds() / 60.0
            if span > window_minutes:
                return None

        reason = (
            f"规则 '{rule.get('name', '')}' 命中攻击链关联："
            + " → ".join(
                f"[步骤{s['step']}:{s['dimension']}] {s['summary']}" for s in matched_steps
            )
        )
        return {"steps": matched_steps, "reason": reason}

    @staticmethod
    def _summarize_event(ev: dict) -> str:
        """为攻击链命中步骤生成简短摘要（用于 reason 展示）."""
        dim = ev.get("dimension")
        data = ev.get("data", {}) or {}
        if dim == "process":
            return f"进程 {data.get('process_name', '?')} cmd={str(data.get('command_line', ''))[:60]}"
        if dim == "connection":
            return f"外连 {data.get('remote_address', '?')}:{data.get('remote_port', '?')}"
        if dim == "registry":
            return f"注册表 {data.get('key_path', '?')}"
        if dim == "persistence":
            return f"持久化 {data.get('type', '?')}/{data.get('name', '?')}"
        if dim == "ioc":
            return f"IOC {data.get('ioc_type', '?')}={data.get('ioc_value', '?')}"
        if dim == "timeline":
            return f"时间线 {data.get('event_type', '?')}:{str(data.get('description', ''))[:60]}"
        return dim or "?"

    # ── 原因构建 ────────────────────────────────────────────────────────

    @staticmethod
    def _build_reason(data_item: dict, rule: dict) -> str:
        """构建规则命中原因说明."""
        rule_name = rule.get("name", "")
        description = rule.get("description", "")
        rule_type = rule.get("rule_type", "")
        condition = rule.get("condition", {})
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except json.JSONDecodeError:
                condition = {}

        if rule_type == "composite":
            return f"规则 '{rule_name}' 命中 (组合条件) — {description}"

        field = condition.get("field", "")
        value = data_item.get(field, "")
        if value:
            return (
                f"规则 '{rule_name}' 命中: "
                f"字段 '{field}' 值 '{str(value)[:100]}' — {description}"
            )
        return f"规则 '{rule_name}' 命中 — {description}"

    # ── v1.3.0 R4-2：攻击链消费封装 ────────────────────────────────────

    @staticmethod
    def get_attack_chain_hits(host_id: int) -> list[dict]:
        """读取引擎已落库的攻击链命中（来自 AnalysisResult.details.attack_chains）.

        AI 仅**叙述**这些命中、绝不重判；此处为统一读取封装，供
        ``ai_task_service._execute_task`` 与报告矩阵消费使用。

        Args:
            host_id: 主机 ID.

        Returns:
            攻击链命中列表（每条含 rule_name/severity/reason/steps）；
            无命中或读取失败返回空列表。
        """
        try:
            from app.models.analysis import AnalysisResult

            analysis = AnalysisResult.get_by_host(host_id)
            if not analysis:
                return []
            details = analysis.get("details")
            if not isinstance(details, dict):
                return []
            hits = details.get("attack_chains")
            if not isinstance(hits, list):
                return []
            return [h for h in hits if isinstance(h, dict)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取攻击链命中失败 host=%d: %s", host_id, exc)
            return []


# ── 注册 7 类 matcher 到 MatcherRegistry（P0-1 适配层）────────
# P0 期注册表直接委派 RuleEngine 既有静态方法；P2 期改为动态加载模块。
from app.rules.matchers.registry import MatcherRegistry  # noqa: E402

MatcherRegistry.register("regex", lambda item, cond, ctx=None: RuleEngine._match_regex(item, cond))
MatcherRegistry.register("list", lambda item, cond, ctx=None: RuleEngine._match_list(item, cond, global_context=ctx))
MatcherRegistry.register("threshold", lambda item, cond, ctx=None: RuleEngine._match_threshold(item, cond))
MatcherRegistry.register("behavior", lambda item, cond, ctx=None: RuleEngine._match_behavior(item, cond, global_context=ctx))
MatcherRegistry.register("composite", lambda item, cond, ctx=None: RuleEngine._match_composite(item, cond, global_context=ctx))
MatcherRegistry.register("exists", lambda item, cond, ctx=None: RuleEngine._match_exists(item, cond))
MatcherRegistry.register("attack_chain", lambda item, cond, ctx=None: False)
