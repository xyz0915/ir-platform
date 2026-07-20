"""MatcherRegistry — 7 类规则匹配注册表（插件式骨架，P0 委派 RuleEngine 方法）.

设计 §3.2 / §8.1：统一 matcher 接口签名
    match(item: dict, condition: dict, global_context: Optional[dict]) -> bool

P0 期注册表直接委派 RuleEngine 既有静态方法（3 参数包装，吸收 global_context）；
P2 期改为可动态加载 matcher 模块（解决插件化），注册表结构不变。

注意：本模块不导入 RuleEngine，避免循环依赖；注册动作由 rule_engine 模块
在类定义完成后调用 MatcherRegistry.register(...) 完成（依赖注入）。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# 统一 matcher 接口签名
MatcherFn = Callable[[dict, dict, Optional[dict]], bool]


class MatcherRegistry:
    """规则匹配器注册表 — 按 rule_type 分发到对应匹配函数."""

    # rule_type -> 匹配函数（3 参数：(item, condition, global_context) -> bool）
    _REGISTRY: dict[str, MatcherFn] = {}

    @classmethod
    def register(cls, rule_type: str, fn: MatcherFn) -> None:
        """注册某类规则的匹配函数（重复注册覆盖）."""
        cls._REGISTRY[rule_type] = fn

    @classmethod
    def dispatch(
        cls,
        rule_type: str,
        item: dict,
        condition: dict,
        global_context: Optional[dict] = None,
    ) -> bool:
        """按 rule_type 分发匹配.

        Args:
            rule_type: 规则类型（regex/list/threshold/behavior/composite/exists/attack_chain）。
            item: 扁平化数据项字典。
            condition: 规则条件字典。
            global_context: 全局上下文（透传 behavior/threshold/composite）。

        Returns:
            是否匹配。未知类型记录警告并返回 False。
        """
        fn = cls._REGISTRY.get(rule_type)
        if fn is None:
            logger.warning("Unknown rule_type: %s（未注册 matcher）", rule_type)
            return False
        try:
            return bool(fn(item, condition, global_context))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Matcher '%s' 执行异常: %s", rule_type, exc)
            return False

    @classmethod
    def registered_types(cls) -> list[str]:
        """返回已注册的规则类型列表."""
        return list(cls._REGISTRY.keys())

    @classmethod
    def list_types(cls) -> list[str]:
        """返回已注册的 matcher 类型列表（T-P2-2c 别名，与 registered_types 同义）."""
        return cls.registered_types()

    @classmethod
    def is_registered(cls, rule_type: str) -> bool:
        """判断某类型是否已注册."""
        return rule_type in cls._REGISTRY
