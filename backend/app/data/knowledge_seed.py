"""内置种子知识数据.

在 ChromaDB 向量库为空时作为初始索引数据源，提供：
- MITRE ATT&CK 技术描述
- 常见 C2 框架特征
- 恶意软件行为模式

所有数据以统一格式提供，兼容 knowledge_retriever 的关键词/向量检索。
"""

# ============================================================================
# MITRE ATT&CK 技术描述（5 条）
# ============================================================================

MITRE_TECHNIQUES: list[dict] = [
    {
        "id": "T1059.001",
        "name": "PowerShell (无文件攻击)",
        "description": (
            "攻击者利用 PowerShell 执行无文件恶意代码，常结合编码、混淆、"
            "反射加载等技术绕过防护。常见特征：-EncodedCommand、-WindowStyle Hidden、"
            "Invoke-Expression (IEX)、DownloadString、反射加载 .NET 程序集。"
        ),
        "tactic": "Execution",
        "severity": "high",
        "category": "mitre_attack",
    },
    {
        "id": "T1546.003",
        "name": "WMI 事件订阅持久化",
        "description": (
            "攻击者通过 WMI 事件订阅（__EventFilter / __EventConsumer / "
            "__FilterToConsumerBinding）实现持久化。当触发条件满足时自动执行"
            "恶意脚本或可执行文件。常见特征：ActiveScriptEventConsumer、"
            "CommandLineEventConsumer、scrcons.exe 子进程异常。"
        ),
        "tactic": "Persistence",
        "severity": "high",
        "category": "mitre_attack",
    },
    {
        "id": "T1547",
        "name": "启动项/登录脚本持久化",
        "description": (
            "攻击者在系统启动或用户登录时自动执行恶意代码。常见位置："
            "Run/RunOnce 注册表键、Startup 文件夹、登录脚本(GPO)、"
            "Winlogon Shell/Userinit 劫持、LSASS 扩展。"
        ),
        "tactic": "Persistence",
        "severity": "medium",
        "category": "mitre_attack",
    },
    {
        "id": "T1055",
        "name": "进程注入",
        "description": (
            "攻击者将恶意代码注入合法进程以隐藏恶意活动并提升权限。常见技术："
            "DLL 注入、PE 注入、进程镂空(Process Hollowing)、"
            "线程执行劫持、AtomBombing、反射 DLL 注入。可疑特征："
            "rundll32/regsvr32 执行无关 DLL、svchost 加载非系统 DLL。"
        ),
        "tactic": "Defense Evasion",
        "severity": "high",
        "category": "mitre_attack",
    },
    {
        "id": "T1071",
        "name": "应用层 C2 协议",
        "description": (
            "攻击者使用标准应用层协议进行 C2 通信以混入正常流量。常见协议："
            "HTTP/HTTPS（Beacon/DNS Beacon）、DNS 隧道、WebSocket、"
            "MQTT、SSH 隧道。特征：周期性外连心跳、异常 User-Agent、"
            "DNS TXT 查询高频、DoH/DoT 绕过 DNS 监控。"
        ),
        "tactic": "Command and Control",
        "severity": "high",
        "category": "mitre_attack",
    },
]

# ============================================================================
# 常见 C2 框架特征（3 条）
# ============================================================================

C2_FRAMEWORKS: list[dict] = [
    {
        "name": "Cobalt Strike",
        "pattern": "cobalt_strike beacon malleable_c2 named_pipe dns_beacon",
        "description": (
            "商业红队/C2 框架，使用 Beacon payload 实现灵活 C2 通信。"
            "支持 Malleable C2 协议伪装、命名管道横向移动、进程注入。"
            "特征：HTTP/HTTPS GET/POST 心跳（特定 URI 模式）、JA3/S 指纹异常、"
            "DNS Beacon（A/AAAA/TXT 记录查询模式异常）、SMB 命名管道 Beacon。"
        ),
        "category": "c2_framework",
        "severity": "critical",
    },
    {
        "name": "Metasploit Framework",
        "pattern": "metasploit meterpreter reverse_tcp reverse_http bind_shell",
        "description": (
            "开源渗透测试/C2 框架，Meterpreter 载荷支持内存驻留无文件攻击。"
            "特征：reverse_tcp/reverse_http(s) 回连、stageless payload、"
            "Meterpreter 反射 DLL 注入、kiwi/mimikatz 扩展加载、"
            "stdapi 文件系统操作痕迹。"
        ),
        "category": "c2_framework",
        "severity": "high",
    },
    {
        "name": "PowerShell Empire",
        "pattern": "empire powershell_empire stager listener http_c2",
        "description": (
            "基于 PowerShell 的后渗透/C2 框架，利用 PowerShell 执行 Agent。"
            "特征：Base64 编码 PowerShell 命令、Invoke-Empire/Invoke-Expression、"
            "WMI 部署 Agent、注册表持久化、无文件内存驻留。"
        ),
        "category": "c2_framework",
        "severity": "high",
    },
]

# ============================================================================
# 恶意软件行为模式（2 条）
# ============================================================================

MALWARE_PATTERNS: list[dict] = [
    {
        "name": "勒索软件行为模式",
        "pattern": (
            "ransomware encrypt file_extension ransom_note shadow_copy_delete "
            "vssadmin wbadmin volume_shadow network_share"
        ),
        "description": (
            "批量加密用户文件并索要赎金。典型行为链：停止数据库/邮件服务 "
            "→ 删除卷影副本(vssadmin delete shadows / wbadmin delete catalog) "
            "→ 遍历本地/网络共享文件批量加密（后缀变更如 .encrypted/.locked）"
            "→ 投放勒索信(README.txt/HOW_TO_DECRYPT.txt) "
            "→ 修改桌面壁纸/自启动注册表项。优先排查：异常加密 I/O 峰值、"
            "大量文件改名事件、vssadmin/wbadmin 命令行调用。"
        ),
        "category": "malware_behavior",
        "severity": "critical",
    },
    {
        "name": "窃密木马行为模式",
        "pattern": (
            "infostealer credential_dump browser_data keylogger "
            "clipboard_hijack screenshot exfiltration"
        ),
        "description": (
            "窃取浏览器保存的密码、Cookie、数字钱包、SSH 密钥等敏感信息并外传。"
            "典型行为：访问浏览器 SQLite 数据库(Cookies/Login Data) "
            "→ 读取/解密凭据 → 压缩打包 → HTTP POST/邮箱外传。"
            "特征：非浏览器进程读取浏览器配置文件、系统凭据转储(procdump/lsass dump)、"
            "异常外连到境外 VPS/对象存储、SMTP/IMAP 邮件外传。"
        ),
        "category": "malware_behavior",
        "severity": "high",
    },
]

# ============================================================================
# 合并后的统一知识列表
# ============================================================================

# 统一列表，供关键词匹配等检索使用。
# 格式兼容 knowledge_retriever._keyword_retrieve() 对规则的匹配逻辑：
# 每条需含 name / description / category / severity 字段。
ALL_SEED_KNOWLEDGE: list[dict] = MITRE_TECHNIQUES + C2_FRAMEWORKS + MALWARE_PATTERNS

# 用于向量索引时的文档集合（name + description 作为文档文本）
SEED_DOCUMENTS: list[dict] = []
for _item in ALL_SEED_KNOWLEDGE:
    SEED_DOCUMENTS.append({
        "id": _item.get("id", _item.get("name", "")),
        "name": _item.get("name", ""),
        "description": _item.get("description", ""),
        "category": _item.get("category", ""),
        "severity": _item.get("severity", "medium"),
        "tactic": _item.get("tactic", ""),
        "pattern": _item.get("pattern", ""),
    })
