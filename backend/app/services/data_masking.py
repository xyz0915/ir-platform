"""数据脱敏引擎 — 纯函数实现，无外部依赖.

提供 IP、路径、用户名、域名的脱敏功能，以及递归字典遍历脱敏.
"""

import json
import re
from typing import Any


def mask_ip(ip: str) -> str:
    """脱敏 IP 地址.

    IPv4: 192.168.1.100 -> 192.168.*.*
    IPv6: 2001:db8::1 -> 2001:db8:****
    """
    if not ip:
        return ip
    if ":" in ip:
        return _mask_ipv6(ip)
    if "." in ip:
        return _mask_ipv4(ip)
    return ip


def _mask_ipv4(ip: str) -> str:
    """IPv4 脱敏：后两段掩码."""
    parts = ip.split(".")
    if len(parts) == 4:
        parts[2] = "*"
        parts[3] = "*"
        return ".".join(parts)
    return ip


def _mask_ipv6(ip: str) -> str:
    """IPv6 脱敏：保留前两段."""
    parts = ip.split(":")
    if len(parts) >= 2:
        return ":".join(parts[:2]) + ":****"
    return ip


def mask_path(path: str) -> str:
    """脱敏路径：保留文件名，路径中用 *** 替代用户名目录.

    C:\\Users\\admin\\恶意.exe -> C:\\Users\\***\\恶意.exe
    /home/user/malware -> /home/***/malware
    """
    if not path:
        return path
    is_windows = "\\" in path
    parts = path.replace("\\", "/").split("/")
    if len(parts) >= 3:
        # 脱敏倒数第二个元素（文件名前的目录，通常是用户名）
        # 也脱敏 Users/ 后面的目录
        for i in range(len(parts) - 1):
            if parts[i].lower() in ("users", "home") and i + 1 < len(parts) - 1:
                parts[i + 1] = "***"
        # 如果文件名前恰好是用户名目录，默认脱敏
        if parts[-2] != "***" and len(parts) >= 3:
            parts[-2] = "***"
    masked = "/".join(parts)
    if is_windows:
        masked = masked.replace("/", "\\")
    return masked


def mask_username(name: str) -> str:
    """脱敏用户名：保留首尾字符，中间用 *** 替代.

    admin -> a***n
    ab -> ab (长度<=2 不脱敏)
    """
    if not name or len(name) <= 2:
        return name
    return name[0] + "***" + name[-1]


def mask_domain(domain: str) -> str:
    """脱敏域名：保留 TLD，主域名中间用 *** 替代.

    evil.com -> e***.com
    test.example.com -> t***.example.com
    """
    if not domain or "." not in domain:
        return domain
    parts = domain.split(".")
    if len(parts) >= 2:
        name = parts[0]
        if len(name) > 1:
            parts[0] = name[0] + "***"
        else:
            parts[0] = name + "***"
    return ".".join(parts)


# 预编译正则模式
_IPV4_PATTERN = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')
_IPV6_PATTERN = re.compile(r'\b([0-9a-fA-F:]+:+[0-9a-fA-F:]+)\b')
_WINDOWS_PATH_PATTERN = re.compile(r'([A-Za-z]:\\[^\s,;"]+)')
_UNIX_PATH_PATTERN = re.compile(r'(/[^\s,;"]{4,})')
_DOMAIN_PATTERN = re.compile(r'\b([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)\b')


def apply(data: dict) -> dict:
    """递归遍历字典，对所有字符串值应用脱敏规则.

    支持嵌套 dict 和 list，对每个字符串值检测：
    - IP 地址 → mask_ip
    - 路径 → mask_path
    - 用户名 → mask_username
    - 域名 → mask_domain
    按优先级依次匹配，命中即停止.

    Args:
        data: 需要脱敏的字典数据.

    Returns:
        脱敏后的字典（深拷贝）.
    """
    return _mask_dict(data)


def _mask_dict(obj: Any) -> Any:
    """递归脱敏处理."""
    if isinstance(obj, dict):
        return {key: _mask_value(key, val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [_mask_dict(item) for item in obj]
    if isinstance(obj, str):
        return _mask_string(obj)
    return obj


def _mask_value(key: str, val: Any) -> Any:
    """根据 key 名和值类型进行脱敏.

    如果值是字符串，先检测 key 是否暗示特殊类型，再对值做模式匹配.
    """
    if isinstance(val, dict):
        return _mask_dict(val)
    if isinstance(val, list):
        return [_mask_dict(item) for item in val]
    if isinstance(val, str):
        # 根据 key 名直接判断
        key_lower = key.lower()
        if key_lower in ("ip", "ip_address", "remote_address", "local_address", "ipv4", "ipv6"):
            return mask_ip(val)
        if key_lower in ("username", "user", "user_name", "account"):
            return mask_username(val)
        if key_lower in ("hostname",):
            # hostname 不用脱敏（应急需要看主机名）
            return val
        # 通用字符串模式匹配
        return _mask_string(val)
    return val


def _mask_string(text: str) -> str:
    """对字符串进行模式匹配脱敏.

    匹配顺序：IPv4 > IPv6 > Windows路径 > Unix路径 > 域名.
    """
    if not text:
        return text

    # IPv4
    def _replace_ipv4(m: re.Match) -> str:
        return _mask_ipv4(m.group(1))

    text = _IPV4_PATTERN.sub(_replace_ipv4, text)

    # IPv6
    def _replace_ipv6(m: re.Match) -> str:
        return _mask_ipv6(m.group(1))

    text = _IPV6_PATTERN.sub(_replace_ipv6, text)

    # Windows 路径
    def _replace_win_path(m: re.Match) -> str:
        return mask_path(m.group(1))

    text = _WINDOWS_PATH_PATTERN.sub(_replace_win_path, text)

    # Unix 路径
    def _replace_unix_path(m: re.Match) -> str:
        return mask_path(m.group(1))

    text = _UNIX_PATH_PATTERN.sub(_replace_unix_path, text)

    return text


def mask_evidence(evidence: Any) -> Any:
    """对 evidence JSON 脱敏（P0-4 导出用）。

    - dict/list → 递归脱敏后原样返回；
    - JSON 字符串 → 先解析再脱敏再 dump（保持字符串类型）；
    - 非 JSON 字符串 → 通用字符串模式脱敏（IP/路径/域名）。

    Args:
        evidence: evidence 列值（JSON 字符串或已解析对象）。

    Returns:
        脱敏后的值（类型与输入一致）。
    """
    if isinstance(evidence, str):
        stripped = evidence.strip()
        if not stripped:
            return evidence
        try:
            parsed = json.loads(stripped)
            return json.dumps(_mask_dict(parsed), ensure_ascii=False)
        except json.JSONDecodeError:
            return _mask_string(evidence)
    return _mask_dict(evidence)
