#!/usr/bin/env python3
"""T8 插件选择器修复 验收脚本。

验收标准（全部满足才 exit 0）：
1. bridge.user.js 中能提取到 `const MESSAGE_SELECTOR = "..."`（单双引号均可）。
2. 用 html.parser 解析 snapshot.html 构建 DOM 树（注释不解析，注释里的旧选择器
   `.message-list` 天然不可命中）。
3. 选择器支持两种形式：类选择器 `.foo` 或属性选择器 `[data-testid=xxx]`
   （引号可有可无）。选择器至少命中 1 个节点。
4. 至少一个被命中的节点，其后代中包含 >= 3 个 class 含 msg-item 的消息子项。

用法：python3 accept_T8.py <workspace>
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

MIN_MATCHES = 1
MIN_MSG_ITEMS = 3


DATA_TESTID_RE = re.compile(r'\[data-testid=["\']?([^\]"\'<>]+)["\']?\]')
SELECTOR_RE = re.compile(r'\[data-testid=["\']?[^\]"\'<>]+["\']?\]')


def fail(msg: str) -> None:
    print(f"[T8 FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent=None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.parent = parent


class DOMBuilder(HTMLParser):
    VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col",
            "embed", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("__root__", [])
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs, self.stack[-1]))

    def handle_endtag(self, tag):
        # 弹栈到匹配标签；容错未闭合标签
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    # handle_comment 不实现：注释节点不进入 DOM 树


def iter_nodes(node):
    yield node
    for c in node.children:
        yield from iter_nodes(c)


def class_tokens(node):
    return (node.attrs.get("class") or "").split()


def matches(node, selector):
    if node.tag == "__root__":
        return False
    if selector.startswith("."):
        return selector[1:] in class_tokens(node)
    m = DATA_TESTID_RE.fullmatch(selector)
    if m:
        return node.attrs.get("data-testid") == m.group(1)
    return False


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: python3 accept_T8.py <workspace>")
    ws = Path(sys.argv[1])
    js_path = ws / "bridge.user.js"
    html_path = ws / "snapshot.html"
    for p in (js_path, html_path):
        if not p.is_file():
            fail(f"缺少文件: {p}")

    js = js_path.read_text(encoding="utf-8")
    m = re.search(r"""MESSAGE_SELECTOR\s*=\s*(["'])(.+?)\1""", js)
    if not m:
        fail("bridge.user.js 中未找到 MESSAGE_SELECTOR 定义")
    selector = m.group(2).strip()
    if not (selector.startswith(".") or SELECTOR_RE.fullmatch(selector)):
        fail(f"选择器 {selector!r} 不是受支持的形式（.class 或 [data-testid=...]）")

    parser = DOMBuilder()
    parser.feed(html_path.read_text(encoding="utf-8"))
    root = parser.root

    hits = [n for n in iter_nodes(root) if matches(n, selector)]
    if len(hits) < MIN_MATCHES:
        fail(f"选择器 {selector!r} 未命中任何节点（注释中的旧 .message-list 不算）")

    for node in hits:
        n_items = sum(1 for d in iter_nodes(node) if "msg-item" in class_tokens(d))
        if n_items >= MIN_MSG_ITEMS:
            print(f"[T8 PASS] 选择器 {selector!r} 命中 {len(hits)} 个节点，"
                  f"容器内含 {n_items} 个 msg-item")
            sys.exit(0)

    fail(f"选择器 {selector!r} 命中 {len(hits)} 个节点，但没有任何一个含 "
         f">= {MIN_MSG_ITEMS} 个 msg-item 子项")


if __name__ == "__main__":
    main()
