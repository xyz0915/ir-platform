"""Seed 脚本 — 为已分析主机灌入 4 张新表的模拟数据，方便前端验证展示.

用法：backend/venv/Scripts/python.exe scripts/seed_test_data.py [host_id]
默认 host_id=4（示例主机 DESKTOP-NCR4EED）.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import init_db
from app.models.analysis import (
    NetworkConnection,
    FileHash,
    WmiSubscription,
    RegistryKey,
)
from app.models.host import Host

init_db()


def seed_network_connections(host_id: int):
    data = [
        {
            "protocol": "TCP",
            "local_addr": "192.168.1.100",
            "local_port": 49152,
            "remote_addr": "203.0.113.50",
            "remote_port": 443,
            "state": "ESTABLISHED",
            "pid": 2840,
            "process_name": "chrome.exe",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "protocol": "TCP",
            "local_addr": "192.168.1.100",
            "local_port": 49153,
            "remote_addr": "185.220.101.1",
            "remote_port": 9001,
            "state": "ESTABLISHED",
            "pid": 6776,
            "process_name": "agent_windows.exe",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "protocol": "TCP",
            "local_addr": "0.0.0.0",
            "local_port": 3389,
            "remote_addr": "0.0.0.0",
            "remote_port": 0,
            "state": "LISTENING",
            "pid": 1232,
            "process_name": "svchost.exe",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "protocol": "UDP",
            "local_addr": "0.0.0.0",
            "local_port": 53,
            "remote_addr": "0.0.0.0",
            "remote_port": 0,
            "state": "LISTENING",
            "pid": 888,
            "process_name": "svchost.exe",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "protocol": "TCP",
            "local_addr": "127.0.0.1",
            "local_port": 8000,
            "remote_addr": "127.0.0.1",
            "remote_port": 50912,
            "state": "ESTABLISHED",
            "pid": 4580,
            "process_name": "python.exe",
            "collected_at": "2026-07-10 10:30:00",
        },
    ]
    count = NetworkConnection.batch_create(host_id, data)
    print(f"  network_connections: {count} 条")


def seed_file_hashes(host_id: int):
    data = [
        {
            "file_path": "E:\\Users\\***\\agent_windows.exe",
            "file_name": "agent_windows.exe",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "is_signed": 0,
            "signer": "",
            "file_size": 245760,
            "product_name": "",
            "product_version": "",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "file_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "file_name": "chrome.exe",
            "sha256": "a1b2c3d4e5f6789012345678901234567890abcdef012345678901234567890",
            "is_signed": 1,
            "signer": "Google LLC",
            "file_size": 2048000,
            "product_name": "Google Chrome",
            "product_version": "120.0.6099.129",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "file_path": "C:\\Windows\\System32\\svchost.exe",
            "file_name": "svchost.exe",
            "sha256": "f1e2d3c4b5a6789012345678901234567890abcdef012345678901234567890",
            "is_signed": 1,
            "signer": "Microsoft Windows",
            "file_size": 51200,
            "product_name": "Microsoft Windows Operating System",
            "product_version": "10.0.19041.1",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "file_path": "E:\\Users\\***\\AppData\\Local\\360Chrome\\Application\\360chrome.exe",
            "file_name": "360chrome.exe",
            "sha256": "b2c3d4e5f6789012345678901234567890abcdef01234567890123456789012",
            "is_signed": 1,
            "signer": "Beijing Qihu Technology Co., Ltd.",
            "file_size": 3145728,
            "product_name": "360极速浏览器",
            "product_version": "14.0.1100.0",
            "collected_at": "2026-07-10 10:30:00",
        },
    ]
    count = FileHash.batch_create(host_id, data)
    print(f"  file_hashes: {count} 条")


def seed_wmi_subscriptions(host_id: int):
    data = [
        {
            "name": "SCM Event Log Consumer",
            "event_filter": {
                "Query": "SELECT * FROM __InstanceCreationEvent WITHIN 60 WHERE TargetInstance ISA 'Win32_NTLogEvent'",
                "QueryLanguage": "WQL",
            },
            "event_consumer": {
                "Destination": "scm_event_handler.dll",
                "CommandLineTemplate": "",
            },
            "binding_type": "__FilterToConsumerBinding",
            "risk_level": "medium",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "name": "SysmonEventMonitor",
            "event_filter": {
                "Query": "SELECT * FROM __InstanceCreationEvent WITHIN 10 WHERE TargetInstance ISA 'Win32_Process'",
                "QueryLanguage": "WQL",
            },
            "event_consumer": {
                "Destination": "C:\\Program Files\\Sysmon\\sysmon_consumer.exe",
                "CommandLineTemplate": "-log C:\\logs\\proc.json",
            },
            "binding_type": "__FilterToConsumerBinding",
            "risk_level": "low",
            "collected_at": "2026-07-10 10:30:00",
        },
    ]
    count = WmiSubscription.batch_create(host_id, data)
    print(f"  wmi_subscriptions: {count} 条")


def seed_registry_keys(host_id: int):
    data = [
        {
            "key_path": "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
            "value_name": "BaiduYunGuanjia",
            "value_type": "REG_SZ",
            "value_data": "\"E:\\Users\\***\\AppData\\Roaming\\baidu\\BaiduNetdisk\\BaiduNetdisk.exe\" AutoRun",
            "last_write_time": "2026-07-03 19:25:00",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "key_path": "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
            "value_name": "cesvc",
            "value_type": "REG_SZ",
            "value_data": "\"e:\\Users\\***\\AppData\\Local\\360Chrome\\Chrome\\Application\\cexhelper.exe\" /b:1:**** /c:1:****",
            "last_write_time": "2026-07-05 12:34:00",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "key_path": "HKLM\\SYSTEM\\CurrentControlSet\\Services\\BaiduNetdisk",
            "value_name": "ImagePath",
            "value_type": "REG_EXPAND_SZ",
            "value_data": "E:\\Users\\***\\AppData\\Roaming\\baidu\\BaiduNetdisk\\BaiduNetdisk.exe",
            "last_write_time": "2026-07-03 19:26:00",
            "collected_at": "2026-07-10 10:30:00",
        },
        {
            "key_path": "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon",
            "value_name": "Shell",
            "value_type": "REG_SZ",
            "value_data": "explorer.exe",
            "last_write_time": "2026-06-15 08:00:00",
            "collected_at": "2026-07-10 10:30:00",
        },
    ]
    count = RegistryKey.batch_create(host_id, data)
    print(f"  registry_keys: {count} 条")


def main():
    host_id = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    host = Host.get_by_id(host_id)
    if not host:
        print(f"主机 {host_id} 不存在，可用主机：")
        from app.database import get_connection
        with get_connection() as conn:
            for row in conn.execute("SELECT id, hostname, status FROM hosts"):
                print(f"  {row['id']}: {row['hostname']} ({row['status']})")
        sys.exit(1)

    print(f"向主机 {host_id} ({host['hostname']}) 灌入模拟数据...")

    seed_network_connections(host_id)
    seed_file_hashes(host_id)
    seed_wmi_subscriptions(host_id)
    seed_registry_keys(host_id)

    print("\n完成！重启后端后刷新浏览器即可在主机详情页看到新数据。")


if __name__ == "__main__":
    main()
