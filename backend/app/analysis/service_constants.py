"""系统服务风险检测 — 常量定义."""

# --- 安全软件服务白名单（小写）---
SECURITY_SERVICES: list[str] = [
    "windefend", "msmpeng", "sense", "wdnisdrv", "wdfilter",
    "securityhealthservice", "wscsvc", "mpssvc",
    "avp", "kavfs", "klnagent",
    "hipsdaemon", "wsctrl", "zhudongfangyu",
    "csfalconservice", "csagent", "sentinelagent",
    "cavp", "cmdagent",
]

# --- 评分权重 ---
SCORING_WEIGHTS: dict[str, int] = {
    "P0-1-TAMPER": 40,
    "P0-2-SHADOW": 35,
    "P1-PRIVESC": 15,
    "P1-REGISTRY": 10,
}

# --- 可信系统路径（小写）---
# 注意：`startswith` 前缀匹配，`c:\\windows\\` 作为通用前缀覆盖所有系统子目录.
TRUSTED_PATHS: list[str] = [
    # 通用 Windows 系统根目录前缀
    "c:\\windows\\",
    # 通用 ProgramData（部分合法第三方服务安装路径）
    "c:\\programdata\\",
    # 具体可信路径（冗余但保证覆盖）
    "c:\\windows\\system32\\",
    "c:\\windows\\syswow64\\",
    "c:\\program files\\",
    "c:\\program files (x86)\\",
    "c:\\windows\\system32\\drivers\\",
    "c:\\windows\\system32\\wbem\\",
    "c:\\windows\\system32\\svchost.exe",
    "c:\\windows\\system32\\services.exe",
]

# --- 常见合法 Windows 服务（小写集合）---
KNOWN_LEGIT_SERVICES: set[str] = {
    "dhcp", "dnscache", "eventlog", "lmhosts", "netman", "nlasvc",
    "plugplay", "rpcss", "samss", "schedule", "seclogon", "spooler", "themes",
    "w32time", "winmgmt", "wuauserv", "bits", "cryptsvc", "dcomlaunch",
    "deviceinstall", "dot3svc", "dxgikrnl", "efs", "fdphost", "fontcache",
    "gpsvc", "hidserv", "ikeext", "iphlpsvc", "kdc", "lanmanserver",
    "lanmanworkstation", "lfsvc", "msdtc", "msiserver", "netlogon",
    "netprofm", "nettcpip6", "nettcpportsharing", "pcasvc", "pciidexdrive",
    "power", "profext", "profsvc", "rasauto", "rasman", "remoteaccess",
    "remoteregistry", "scpolicy", "sensrsvc", "sessionenv", "shellhwdetection",
    "smstsmgr", "snmptrap", "ssdpsrv", "stisvc", "swprv", "sysmain",
    "tapisrv", "tdxdointcp", "termservice", "trkwks", "trustedinstaller",
    "uhssvc", "umrdpservice", "upnphost", "vds", "vss", "wbengine",
    "wcncsvc", "wcssvc", "wdiwifi", "wecsvc", "wephostsvc", "werrorsvc",
    "wersvc", "wiadefault", "wisvc", "wlansvc", "wlpasvc", "wmpnetworksvc",
    "wpcsvc", "wpnservice", "ws2ifsl", "wsearch", "wudfsvc", "xbgamesave",
    "xblauthmanager", "xblgamesave",
}

# --- 启动类型风险分值 ---
START_TYPE_RISK: dict[str, int] = {
    "disabled": 20,
    "manual": 5,
    "auto": 0,
    "delayed-auto": 0,
    "boot": 0,
    "system": 0,
}

# --- 名字相似度阈值 ---
SERVICE_NAME_SIMILARITY_THRESHOLD: float = 0.85

# --- 可疑路径关键词 ---
SUSPICIOUS_PATH_KEYWORDS: list[str] = [
    "temp", "tmp", "appdata", "downloads", "public", "desktop",
    "users\\", "perflogs",
]
