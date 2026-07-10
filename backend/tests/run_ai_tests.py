#!/usr/bin/env python3
"""AI分析模块测试总入口.

运行所有 AI 模块测试：
    test_data_masking.py    — 数据脱敏引擎
    test_retry_handler.py   — 重试与断路器
    test_ai_audit.py        — 审计日志
    test_ai_config.py       — AI配置Profile
    test_ai_analysis.py     — 报告版本管理
    test_ai_api.py          — API端点
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Suppress deprecation warnings from the codebase
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)


def run_tests():
    """运行所有 AI 测试模块."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_modules = [
        "test_data_masking",
        "test_retry_handler",
        "test_ai_audit",
        "test_ai_config",
        "test_ai_analysis",
        "test_ai_api",
        "test_p2_features",
    ]

    for module_name in test_modules:
        try:
            module_tests = loader.loadTestsFromName(module_name)
            suite.addTests(module_tests)
        except Exception as e:
            print(f"  [ERROR] Failed to load {module_name}: {e}")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


if __name__ == "__main__":
    print("=" * 70)
    print("  AI 分析模块 — 综合测试套件")
    print("=" * 70)
    print()

    result = run_tests()

    print()
    print("=" * 70)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"  AI Tests: {passed}/{result.testsRun} passed")
    print(f"  Failures: {len(result.failures)}")
    print(f"  Errors: {len(result.errors)}")
    print("=" * 70)

    sys.exit(0 if result.wasSuccessful() else 1)
