# 规则目录（Rules Catalog）

> 自动生成自 backend/app/rules/default_rules.json。本文档描述平台内置默认规则（source=default）。
> 用户通过 API 创建的规则（source=user）不在此目录中。

**规则总数**: 102

**严重程度分布**: high=55（53.9%），medium=24（23.5%），critical=21（20.6%），low=2（2.0%）

> 说明：严重程度按检测技术对应的攻击者目标影响分级（保守 rubric）。credential/impact/lateral/ioc=严重；
> privilege_escalation/defense_evasion/persistence/exfiltration/execution/network=高危；behavior/process/discovery/startup=中危；噪声型启发式=低危。

## 按类别分组

### behavior（8）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| orphan_process | 孤立进程（无父进程） | behavior | medium | T1059 |
| suspicious_parent_child | 办公软件启动脚本解释器 | behavior | medium | T1566/001 |
| unsigned_process | 非系统目录进程 | behavior | low | T1036 |
| high_connection_count | 进程连接数异常 | threshold | medium | T1041 |
| remote_desktop_suspicious | 可疑远程控制软件 | regex | low | T1219 |
| process_chain_attack | 进程链攻击路径 | behavior | critical | T1059/001 |
| time_cluster_burst | 时间聚类异常爆发 | behavior | high | T1071 |
| short_lived_shell | 短存活 Shell 进程 | behavior | medium | T1059/001 |

### credential（9）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| lsass_dump_detection | LSASS 凭据转储 | behavior | critical | T1003/001 |
| sam_dump_detection | SAM 注册表导出 | regex | critical | T1003/002 |
| ntds_dump_detection | NTDS.dit 域控导出 | regex | critical | T1003/003 |
| dpapi_credential_theft | DPAPI 凭据窃取 | regex | critical | T1003/004 |
| browser_credential_theft | 浏览器凭据窃取 | regex | critical | T1003 |
| lsa_secrets_dump | LSA Secrets 导出 | regex | critical | T1003/004 |
| credential_dump_behavior | 凭据导出综合行为 | behavior | critical | T1003 |
| kerberoasting_detection | Kerberoasting 攻击 | regex | critical | T1558/003 |
| dcsync_detection | DCSync 攻击 | regex | critical | T1003/006 |

### defense_evasion（9）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| obfuscated_execution_evasion | 混淆执行绕过检测 | regex | high | T1027 |
| log_clearing_evasion | 日志清除规避 | behavior | high | T1070 |
| security_product_disable | 安全产品禁用 | behavior | high | T1562/001 |
| code_signing_bypass | 代码签名绕过 | regex | high | T1553/006 |
| process_injection_indicator | 进程注入特征 | regex | high | T1055 |
| amsi_bypass_attempt | AMSI 绕过尝试 | regex | high | T1562/001 |
| sysmon_tampering | Sysmon 干扰卸载 | regex | high | T1562/001 |
| parent_pid_spoofing | 父进程 PID 欺骗 | regex | high | T1134/004 |
| reflective_dll_injection | 反射式 DLL 注入 | regex | high | T1055 |

### discovery（7）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| system_discovery_recon | 系统信息探测 | behavior | medium | T1082 |
| network_scan_behavior | 网络扫描行为 | behavior | medium | T1046 |
| domain_discovery_commands | 域环境探测命令 | regex | medium | T1482 |
| sensitive_file_search | 敏感文件搜索 | regex | medium | T1083 |
| data_staging_directory | 数据暂存目录 | composite | medium | T1074/001 |
| clipboard_capture | 剪贴板数据捕获 | regex | medium | T1115 |
| smb_share_enumeration | SMB 共享枚举 | regex | medium | T1135 |

### execution（11）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| dotnet_inline_compilation | DotNet 内联编译执行（无文件） | regex | high | T1059/001 |
| msbuild_inline_task_execution | MSBuild 内联任务执行（无文件 LOLBin） | regex | high | T1127/001 |
| msiexec_remote_lolbin | MSIExec 远程下载执行（LOLBin） | regex | high | T1218/007 |
| phishing_doc_macro | 钓鱼文档宏执行 | composite | high | T1566/001 |
| exploit_script_download | 漏洞利用脚本下载执行 | regex | high | T1203 |
| malicious_macro_indicator | 恶意宏特征 | regex | high | T1566/001 |
| wmic_lolbin_execution | WMIC LOLBin 执行 | regex | high | T1047 |
| cmd_obfuscated_execution | CMD 混淆执行 | regex | high | T1059/003 |
| powershell_download_cradle | PowerShell 下载 Cradle | regex | high | T1059/001 |
| mshta_inline_script | MSHTA 内联脚本执行 | regex | high | T1218/005 |
| cscript_wscript_download | CScript/WScript 下载执行 | regex | high | T1059/005 |

### exfiltration（3）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| data_compression_exfil | 数据压缩外传 | behavior | high | T1048 |
| dns_tunnel_exfil | DNS 隧道外传 | regex | high | T1048/003 |
| icmp_tunnel_exfil | ICMP 隧道外传 | regex | high | T1048/003 |

### impact（2）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| ransomware_behavior_pattern | 勒索软件行为 | behavior | critical | T1486 |
| data_destruction_indicator | 数据破坏检测 | regex | critical | T1485 |

### ioc（3）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| known_bad_ip_1 | 已知恶意 IP 185.220.101.x | list | critical | T1571 |
| known_bad_ip_2 | 已知恶意 IP 104.244.72.x | list | critical | T1571 |
| known_bad_ip_3 | 已知恶意 IP 91.219.236.x | list | critical | T1571 |

### lateral（6）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| psexec_lateral_movement | PSExec 横向移动 | regex | critical | T1570 |
| wmi_remote_execution | WMI 远程执行 | behavior | critical | T1047 |
| rdp_tunnel_detection | RDP 隧道检测 | regex | critical | T1021/001 |
| ssh_lateral_tunnel | SSH 横向隧道 | regex | critical | T1572 |
| pass_the_hash_detection | Pass-the-Hash 攻击 | regex | critical | T1550/002 |
| scheduled_task_lateral | 计划任务远程创建 | regex | critical | T1053/005 |

### network（12）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| c2_port_4444 | C2 端口 4444 | list | high | T1571 |
| c2_port_6667 | C2 端口 6667 (IRC) | list | high | T1571 |
| c2_port_1337 | C2 端口 1337 | list | high | T1571 |
| c2_port_4443 | C2 端口 4443 | list | high | T1571 |
| c2_port_5555 | C2 端口 5555 (ADB) | list | high | T1571 |
| c2_port_8888 | C2 端口 8888 | list | high | T1571 |
| suspicious_c2_domain | 已知恶意 C2 域名 | list | high | T1571 |
| known_c2_framework | 已知 C2 框架特征 | regex | high | T1571 |
| dns_c2_beaconing | DNS C2 Beaconing | threshold | high | T1571 |
| domain_fronting_detection | 域前置检测 | regex | high | T1572 |
| webshell_file_detection | WebShell 文件检测 | regex | high | T1505/003 |
| webshell_process_activity | WebShell 进程活动 | behavior | high | T1505/003 |

### persistence（13）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| suspicious_scheduled_task_xml_exists | 存在可疑计划任务定义 | exists | high | T1053/005 |
| suspicious_service_reg_exists | 存在可疑服务注册项 | exists | high | T1543/003 |
| suspicious_scheduled_task | 可疑计划任务脚本 | regex | high | T1053/005 |
| suspicious_service_path | 服务路径指向非系统目录 | regex | high | T1543/003 |
| wmi_subscription | WMI 事件订阅持久化 | regex | high | T1546/003 |
| hidden_cron_job | 隐藏 Cron 任务 | regex | high | T1053/003 |
| wmi_persistence_behavior | WMI 持久化行为 | behavior | high | T1546/003 |
| com_hijack_persistence | COM 劫持持久化 | behavior | high | T1546/015 |
| image_file_execution_hijack | 映像劫持 (IFEO) | regex | high | T1546/012 |
| dll_search_order_hijack | DLL 搜索顺序劫持 | behavior | high | T1574/001 |
| appinit_dlls_persistence | AppInit_DLLs 持久化 | regex | high | T1546/010 |
| screensaver_persistence | 屏幕保护程序持久化 | regex | high | T1546/002 |
| dll_hijack_behavior | DLL 侧加载行为 | behavior | high | T1574/002 |

### privilege_escalation（6）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| uac_bypass_detection | UAC 绕过检测 | behavior | high | T1548/002 |
| token_theft_escalation | Token 窃取提权 | behavior | high | T1134 |
| service_permission_escalation | 服务权限提升 | regex | high | T1543/003 |
| scheduled_task_escalation | 计划任务权限提升 | regex | high | T1053/005 |
| sticky_keys_escalation | 辅助功能替换提权 | regex | high | T1546/008 |
| privilege_escalation_composite | 权限提升综合检测 | composite | high | T1548 |

### process（10）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| powershell_encoded_command | PowerShell 编码命令执行 | regex | medium | T1059/001 |
| powershell_bypass_execution | PowerShell 绕过执行策略 | regex | medium | T1059/001 |
| certutil_download | Certutil 下载文件 | regex | medium | T1105 |
| bitsadmin_download | Bitsadmin 下载文件 | regex | medium | T1197 |
| suspicious_mshta | Mshta 执行远程脚本 | regex | medium | T1218/005 |
| regsvr32_squiblydoo | Regsvr32 Squiblydoo 远程脚本 | regex | medium | T1218/011 |
| wmic_process_create | WMIC 远程进程创建 | regex | medium | T1047 |
| rundll32_suspicious | Rundll32 加载可疑模块 | regex | medium | T1218/011 |
| cmd_powershell_chain | CMD 启动 PowerShell 链 | regex | medium | T1059/001 |
| nc_netcat_listener | Netcat 监听后门 | regex | medium | T1571 |

### startup（3）

| 英文键 (name) | 中文名称 (label) | 类型 | 严重程度 | MITRE ATT&CK |
| --- | --- | --- | --- | --- |
| suspicious_run_key | 可疑 Run 键启动项 | regex | medium | T1547/001 |
| startup_temp_path | 启动项指向临时目录 | regex | medium | T1547/001 |
| suspicious_startup_folder | 启动文件夹可执行文件 | regex | medium | T1547/001 |

---

## 规则类型说明

- **regex**：字段正则匹配（如命令行的混淆/编码特征）。
- **list**：黑名单值匹配（如恶意 IP/端口）。
- **threshold**：数值阈值异常（如连接数突增）。
- **behavior**：引擎内置 20 种行为模式（orphan_process / credential_dump / ransomware_behavior / process_chain / time_cluster / short_lived 等）。
- **composite**：AND/OR 递归组合子规则。
- **exists**：字段存在性检查（如可疑计划任务 XML / 可疑服务注册表项）。
