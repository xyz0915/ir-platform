"""轻量字段 DSL 解析器 — 白名单字段 + AND/OR/NOT + 操作符（P0-1）。

语法（§2.3.1）：:

    expr       := or_expr
    or_expr    := and_expr ( "or" and_expr )*
    and_expr   := unary ( "and" unary )*
    unary      := "not" unary | "(" expr ")" | condition
    condition  := field op value
    field      := [a-zA-Z_][a-zA-Z0-9_]*          # 必须命中 DSL_FIELDS 白名单
    op         := "==" | "!=" | ">=" | "<=" | ">" | "<" | "~" | "in" | "between"
    value      := STRING | NUMBER | list
    STRING     := '"' ... '"' | "'" ... "'"
    list       := "(" value ("," value)* ")" 或 "[" value ("," value)* "]"
    bare       := 裸词（无 field）→ keyword contains（多个裸词 AND）

安全红线：字段名仅取白名单 key；值一律参数绑定（由 field_query_map
编译为 ``?`` 绑定）；``dsl`` 长度 ≤ 500、条件数 ≤ 20、禁止危险字符；
解析失败抛 ``DSLError``（端点层转 400 + 定位信息）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from app.services.field_query_map import (
    COLUMN_FIELDS,
    EVIDENCE_JSON_FIELDS,
    KEYWORD_FALLBACK_FIELDS,
)

# DSL 字段白名单（三级映射 key + keyword）
DSL_FIELDS = (
    set(COLUMN_FIELDS.keys())
    | set(EVIDENCE_JSON_FIELDS.keys())
    | set(KEYWORD_FALLBACK_FIELDS)
    | {"keyword"}
)

# 危险字符（注入尝试）
_DANGEROUS = re.compile(
    r";|--|/\*|\*/|xp_|\b(drop|delete|update|insert|alter|truncate|create|replace)\b",
    re.IGNORECASE,
)

MAX_DSL_LENGTH = 500
MAX_CONDITIONS = 20


class DSLError(ValueError):
    """DSL 语法/安全错误（端点层转 400）。"""

    def __init__(self, message: str, pos: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.pos = pos

    def __str__(self) -> str:
        if self.pos is not None:
            return f"{self.message} (位置 {self.pos})"
        return self.message


@dataclass
class Token:
    """词法单元。"""

    kind: str
    value: str
    pos: int = -1


# ── AST 节点 ──────────────────────────────────────────────────


@dataclass
class Node:
    """DSL AST 基类。"""


@dataclass
class And(Node):
    left: Any
    right: Any


@dataclass
class Or(Node):
    left: Any
    right: Any


@dataclass
class Not(Node):
    child: Any


@dataclass
class Condition(Node):
    field: str
    op: str
    value: Any


@dataclass
class Keyword(Node):
    value: str


# ── 词法分析 ──────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"""
    (?P<WS>\s+)
  | (?P<OP>==|!=|>=|<=|>|<|~)
  | (?P<BETWEEN>\bbetween\b)
  | (?P<IN>\bin\b)
  | (?P<AND>\band\b)
  | (?P<OR>\bor\b)
  | (?P<NOT>\bnot\b)
  | (?P<LPAREN>\()
  | (?P<RPAREN>\))
  | (?P<LBRACKET>\[)
  | (?P<RBRACKET>\])
  | (?P<COMMA>,)
  | (?P<STRING>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<NUMBER>-?\d+(?:\.\d+)?)
  | (?P<IDENT>[a-zA-Z_][a-zA-Z0-9_]*)
  | (?P<BARE>[^\s"'(),\[\]]+)
    """,
    re.VERBOSE,
)


def _unescape(s: str) -> str:
    """解码字符串中的 \\" 与 \\' 转义。"""
    return s.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")


def tokenize(expr: str) -> list[Token]:
    """分词：IDENT / OP / AND / OR / NOT / IN / BETWEEN / LPAREN / RPAREN /
    LBRACKET / RBRACKET / STRING / NUMBER / COMMA / BARE。

    Args:
        expr: DSL 表达式。

    Returns:
        Token 列表（末尾含 EOF）。

    Raises:
        DSLError: 无法识别的字符（含位置）。
    """
    tokens: list[Token] = []
    pos = 0
    text = expr or ""
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise DSLError(f"无法识别的字符 {text[pos]!r}", pos)
        kind = m.lastgroup
        value = m.group()
        start = m.start()
        pos = m.end()
        if kind == "WS":
            continue
        if kind == "STRING":
            tokens.append(Token("STRING", _unescape(value[1:-1]), start))
        elif kind == "NUMBER":
            tokens.append(Token("NUMBER", value, start))
        else:
            tokens.append(Token(kind, value, start))
    tokens.append(Token("EOF", "", len(text)))
    return tokens


# ── 递归下降解析 ──────────────────────────────────────────────


class _Parser:
    """递归下降解析器：expr → or_expr → and_expr → unary → condition。"""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.idx = 0

    def peek(self) -> Token:
        return self.tokens[self.idx]

    def advance(self) -> Token:
        t = self.tokens[self.idx]
        if t.kind != "EOF":
            self.idx += 1
        return t

    def expect(self, kind: str) -> Token:
        t = self.peek()
        if t.kind != kind:
            raise DSLError(f"期望 {kind}，实际 {t.kind} {t.value!r}", t.pos)
        return self.advance()

    def parse_expr(self) -> Node:
        return self.parse_or()

    def parse_or(self) -> Node:
        node = self.parse_and()
        while self.peek().kind == "OR":
            self.advance()
            right = self.parse_and()
            node = Or(left=node, right=right)
        return node

    def parse_and(self) -> Node:
        node = self.parse_unary()
        # 隐式 AND：连续裸词（如 `powershell -enc` → keyword contains x2）
        while self.peek().kind in ("IDENT", "BARE", "STRING", "NUMBER"):
            right = self.parse_unary()
            node = And(left=node, right=right)
        while self.peek().kind == "AND":
            self.advance()
            right = self.parse_unary()
            node = And(left=node, right=right)
        return node

    def parse_unary(self) -> Node:
        t = self.peek()
        if t.kind == "NOT":
            self.advance()
            child = self.parse_unary()
            return Not(child=child)
        if t.kind == "LPAREN":
            self.advance()
            node = self.parse_expr()
            self.expect("RPAREN")
            return node
        return self.parse_condition()

    def parse_condition(self) -> Node:
        t = self.peek()
        if t.kind == "IDENT":
            field = self.advance().value
            nxt = self.peek()
            if nxt.kind in ("OP", "IN", "BETWEEN"):
                return self.parse_typed_condition(field)
            # 裸词：IDENT 无操作符 → keyword contains
            return Keyword(value=field)
        if t.kind in ("BARE", "STRING", "NUMBER"):
            self.advance()
            return Keyword(value=t.value)
        raise DSLError(f"期望字段名或关键词，实际 {t.kind} {t.value!r}", t.pos)

    def parse_typed_condition(self, field: str) -> Node:
        if field not in DSL_FIELDS:
            raise DSLError(f"字段 {field!r} 不在白名单", self.peek().pos - len(field))
        t = self.advance()  # OP / IN / BETWEEN
        if t.kind == "BETWEEN":
            v1 = self.parse_value()
            self.expect("AND")
            v2 = self.parse_value()
            return And(
                left=Condition(field=field, op=">=", value=v1),
                right=Condition(field=field, op="<=", value=v2),
            )
        if t.kind == "IN":
            vals = self.parse_list()
            return Condition(field=field, op="in", value=vals)
        # OP token：== != >= <= > < ~
        op = _OP_MAP.get(t.value)
        if op is None:
            raise DSLError(f"不支持的操作符 {t.value!r}", t.pos)
        value = self.parse_value()
        return Condition(field=field, op=op, value=value)

    def parse_value(self) -> Any:
        t = self.peek()
        if t.kind in ("STRING", "NUMBER"):
            self.advance()
            if t.kind == "NUMBER":
                try:
                    return int(t.value)
                except ValueError:
                    return float(t.value)
            return t.value
        if t.kind in ("IDENT", "BARE"):
            # 裸值（如 status==pending）
            self.advance()
            return t.value
        raise DSLError(f"期望值，实际 {t.kind} {t.value!r}", t.pos)

    def parse_list(self) -> list[Any]:
        t = self.peek()
        if t.kind == "LPAREN":
            close_kind = "RPAREN"
            self.advance()
        elif t.kind == "LBRACKET":
            close_kind = "RBRACKET"
            self.advance()
        else:
            raise DSLError("期望列表 ( ... ) 或 [ ... ]", t.pos)
        vals: list[Any] = []
        if self.peek().kind != close_kind:
            vals.append(self.parse_value())
            while self.peek().kind == "COMMA":
                self.advance()
                vals.append(self.parse_value())
        self.expect(close_kind)
        return vals


# 操作符映射（~ → contains）
_OP_MAP = {
    "==": "=",
    "!=": "!=",
    ">=": ">=",
    "<=": "<=",
    ">": ">",
    "<": "<",
    "~": "contains",
}


def parse(tokens: list[Token]) -> Node:
    """递归下降解析：返回 AST 根节点。

    Raises:
        DSLError: 语法错误（含位置）。
    """
    parser = _Parser(tokens)
    node = parser.parse_expr()
    t = parser.peek()
    if t.kind != "EOF":
        raise DSLError(f"表达式末尾有多余内容 {t.value!r}", t.pos)
    return node


# ── AST → field_conditions ────────────────────────────────────


def to_conditions(ast: Node) -> list[dict]:
    """AST → 树形 field_conditions（list 包装根节点，与 build_where_clause 同构）。

    Returns:
        [root_node]，root_node 为叶子 {"field","op","value"} 或逻辑节点
        {"logic": "and"|"or"|"not", ...}。
    """
    return [_node_to_dict(ast)]


def _node_to_dict(node: Node) -> dict:
    if isinstance(node, And):
        return {"logic": "and", "children": [_node_to_dict(node.left), _node_to_dict(node.right)]}
    if isinstance(node, Or):
        return {"logic": "or", "children": [_node_to_dict(node.left), _node_to_dict(node.right)]}
    if isinstance(node, Not):
        return {"logic": "not", "child": _node_to_dict(node.child)}
    if isinstance(node, Condition):
        return {"field": node.field, "op": node.op, "value": node.value}
    if isinstance(node, Keyword):
        return {"field": "keyword", "op": "contains", "value": node.value}
    raise DSLError("未知 AST 节点")


def _count_conditions(node: Any) -> int:
    """统计条件叶子数量（含 keyword）。"""
    if isinstance(node, dict):
        if node.get("logic") == "not":
            return _count_conditions(node.get("child"))
        if node.get("logic"):
            return sum(_count_conditions(c) for c in node.get("children", []))
        return 1
    return 1


# ── 公开接口 ──────────────────────────────────────────────────


def validate_security(expr: str) -> None:
    """长度/条件数/危险字符检查（parse 前调用）。

    Raises:
        DSLError: 安全校验失败。
    """
    if expr is None or not str(expr).strip():
        return
    text = str(expr)
    if len(text) > MAX_DSL_LENGTH:
        raise DSLError(f"dsl 长度超过上限 {MAX_DSL_LENGTH}")
    if _DANGEROUS.search(text):
        raise DSLError("dsl 包含危险字符（注入尝试被拒绝）")


def compile_to_conditions(expr: str) -> tuple[list[dict], list[str]]:
    """parse + to_conditions；返回 (field_conditions, warnings)。

    Args:
        expr: DSL 表达式（空 → ([], [])）。

    Returns:
        (field_conditions, warnings)。

    Raises:
        DSLError: 语法/安全错误（携带错误位置）。
    """
    validate_security(expr)
    text = (expr or "").strip()
    if not text:
        return [], []
    tokens = tokenize(text)
    ast = parse(tokens)
    conditions = to_conditions(ast)
    if _count_conditions(conditions[0]) > MAX_CONDITIONS:
        raise DSLError(f"条件数超过上限 {MAX_CONDITIONS}")
    warnings: list[str] = []
    return conditions, warnings
