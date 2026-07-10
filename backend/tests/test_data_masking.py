"""数据脱敏引擎测试套件.

测试范围:
    - mask_ip (IPv4 / IPv6 / 边界)
    - mask_path (Windows / Unix / 边界)
    - mask_username (正常 / 短名 / 空)
    - mask_domain (正常 / 子域名 / 边界)
    - apply (递归字典脱敏)
"""

import unittest

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.data_masking import (
    mask_ip,
    mask_path,
    mask_username,
    mask_domain,
    apply,
)


class TestMaskIp(unittest.TestCase):
    """测试 IP 地址脱敏."""

    def test_mask_ipv4_standard(self):
        """IPv4: 192.168.1.100 -> 192.168.*.*"""
        result = mask_ip("192.168.1.100")
        self.assertEqual(result, "192.168.*.*")

    def test_mask_ipv4_another(self):
        """IPv4: 10.0.0.1 -> 10.0.*.*"""
        result = mask_ip("10.0.0.1")
        self.assertEqual(result, "10.0.*.*")

    def test_mask_ipv4_loopback(self):
        """IPv4: 127.0.0.1 -> 127.0.*.*"""
        result = mask_ip("127.0.0.1")
        self.assertEqual(result, "127.0.*.*")

    def test_mask_ipv6_standard(self):
        """IPv6: 2001:db8::1 -> 2001:db8:****"""
        result = mask_ip("2001:db8::1")
        self.assertEqual(result, "2001:db8:****")

    def test_mask_ipv6_full(self):
        """IPv6: 2001:0db8:85a3:0000:0000:8a2e:0370:7334 -> 2001:0db8:****"""
        result = mask_ip("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        self.assertEqual(result, "2001:0db8:****")

    def test_mask_ip_empty(self):
        """空字符串原样返回."""
        result = mask_ip("")
        self.assertEqual(result, "")

    def test_mask_ip_none_equivalent(self):
        """None 等价为空字符串."""
        result = mask_ip(None)
        self.assertIsNone(result)


class TestMaskPath(unittest.TestCase):
    """测试路径脱敏."""

    def test_mask_path_windows_users(self):
        """Windows路径: C:\\Users\\admin\\malware.exe -> C:\\Users\\***\\malware.exe"""
        result = mask_path("C:\\Users\\admin\\malware.exe")
        self.assertEqual(result, "C:\\Users\\***\\malware.exe")

    def test_mask_path_windows_generic(self):
        """Windows路径(倒数第二个目录脱敏): C:\\Temp\\user\\file.txt -> C:\\Temp\\***\\file.txt"""
        result = mask_path("C:\\Temp\\user\\file.txt")
        self.assertEqual(result, "C:\\Temp\\***\\file.txt")

    def test_mask_path_unix_home(self):
        """Unix路径: /home/user/malware -> /home/***/malware"""
        result = mask_path("/home/user/malware")
        self.assertEqual(result, "/home/***/malware")

    def test_mask_path_unix_generic(self):
        """Unix路径(倒数第二个目录脱敏): /var/log/app/output.log -> /var/log/***/output.log"""
        result = mask_path("/var/log/app/output.log")
        self.assertEqual(result, "/var/log/***/output.log")

    def test_mask_path_short(self):
        """短路径: /etc/hosts -> /***/hosts (mask_path总是脱敏倒数第二个目录)"""
        result = mask_path("/etc/hosts")
        self.assertEqual(result, "/***/hosts")

    def test_mask_path_empty(self):
        """空路径原样返回."""
        result = mask_path("")
        self.assertEqual(result, "")

    def test_mask_path_single_segment(self):
        """单段路径: file.txt -> file.txt"""
        result = mask_path("file.txt")
        self.assertEqual(result, "file.txt")


class TestMaskUsername(unittest.TestCase):
    """测试用户名脱敏."""

    def test_mask_username_admin(self):
        """admin -> a***n"""
        result = mask_username("admin")
        self.assertEqual(result, "a***n")

    def test_mask_username_long(self):
        """administrator -> a***r"""
        result = mask_username("administrator")
        self.assertEqual(result, "a***r")

    def test_mask_username_short_2char(self):
        """ab 长度<=2 不脱敏."""
        result = mask_username("ab")
        self.assertEqual(result, "ab")

    def test_mask_username_single_char(self):
        """a 长度<2 不脱敏."""
        result = mask_username("a")
        self.assertEqual(result, "a")

    def test_mask_username_empty(self):
        """空字符串原样返回."""
        result = mask_username("")
        self.assertEqual(result, "")

    def test_mask_username_chinese(self):
        """中文用户名: 张三 -> 张三 (len<=2 不脱敏)"""
        result = mask_username("张三")
        self.assertEqual(result, "张三")


class TestMaskDomain(unittest.TestCase):
    """测试域名脱敏."""

    def test_mask_domain_simple(self):
        """evil.com -> e***.com"""
        result = mask_domain("evil.com")
        self.assertEqual(result, "e***.com")

    def test_mask_domain_single_char(self):
        """a.com -> a***.com"""
        result = mask_domain("a.com")
        self.assertEqual(result, "a***.com")

    def test_mask_domain_subdomain(self):
        """test.example.com -> t***.example.com"""
        result = mask_domain("test.example.com")
        self.assertEqual(result, "t***.example.com")

    def test_mask_domain_multi_subdomain(self):
        """api.v1.mysite.com -> a***.v1.mysite.com"""
        result = mask_domain("api.v1.mysite.com")
        self.assertEqual(result, "a***.v1.mysite.com")

    def test_mask_domain_empty(self):
        """空域名原样返回."""
        result = mask_domain("")
        self.assertEqual(result, "")

    def test_mask_domain_no_dot(self):
        """无点的字符串原样返回."""
        result = mask_domain("localhost")
        self.assertEqual(result, "localhost")


class TestMaskApply(unittest.TestCase):
    """测试递归字典脱敏 apply()."""

    def test_apply_flat_dict(self):
        """测试扁平字典的脱敏."""
        data = {
            "ip": "192.168.1.100",
            "username": "admin",
            "hostname": "SERVER01",
        }
        result = apply(data)
        self.assertEqual(result["ip"], "192.168.*.*")
        self.assertEqual(result["username"], "a***n")
        # hostname 不脱敏
        self.assertEqual(result["hostname"], "SERVER01")

    def test_apply_nested_dict(self):
        """测试嵌套字典的递归脱敏."""
        data = {
            "host": {
                "ip": "10.0.0.1",
                "account": "root",
            },
            "connections": [
                {"remote_address": "185.220.101.1"},
                {"remote_address": "192.168.1.50"},
            ],
        }
        result = apply(data)
        self.assertEqual(result["host"]["ip"], "10.0.*.*")
        self.assertEqual(result["host"]["account"], "r***t")
        self.assertEqual(result["connections"][0]["remote_address"], "185.220.*.*")
        self.assertEqual(result["connections"][1]["remote_address"], "192.168.*.*")

    def test_apply_empty_dict(self):
        """空字典."""
        result = apply({})
        self.assertEqual(result, {})

    def test_apply_non_string_types(self):
        """测试非字符串类型不被修改."""
        data = {
            "count": 42,
            "enabled": True,
            "score": 3.14,
        }
        result = apply(data)
        self.assertEqual(result["count"], 42)
        self.assertEqual(result["enabled"], True)
        self.assertEqual(result["score"], 3.14)

    def test_apply_key_based_masking(self):
        """测试根据 key 名称进行脱敏."""
        data = {
            "ip_address": "172.16.0.1",
            "user_name": "john_doe",
            "remote_address": "8.8.8.8",
            "local_address": "10.1.1.1",
        }
        result = apply(data)
        self.assertEqual(result["ip_address"], "172.16.*.*")
        self.assertEqual(result["user_name"], "j***e")
        self.assertEqual(result["remote_address"], "8.8.*.*")
        self.assertEqual(result["local_address"], "10.1.*.*")

    def test_apply_string_with_embedded_ip(self):
        """测试嵌入在字符串中的 IP 脱敏."""
        data = {
            "description": "连接来自 192.168.1.100 到 10.0.0.5",
        }
        result = apply(data)
        # 字符串中嵌入的 IP 会被脱敏
        self.assertIn("192.168.*.*", result["description"])
        self.assertIn("10.0.*.*", result["description"])
        self.assertNotIn("192.168.1.100", result["description"])

    def test_apply_preserves_structure(self):
        """测试脱敏后字典结构不变."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "ip": "1.1.1.1",
                    },
                },
            },
        }
        result = apply(data)
        self.assertIn("level1", result)
        self.assertIn("level2", result["level1"])
        self.assertIn("level3", result["level1"]["level2"])
        self.assertEqual(result["level1"]["level2"]["level3"]["ip"], "1.1.*.*")


if __name__ == "__main__":
    unittest.main(verbosity=2)
