"""界面自省：把可见控件树的文本导出来（自动化验证用，不参与产品逻辑）。"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


def _collect(widget, out: list[str], depth: int = 0, max_depth: int = 40) -> None:
    if depth > max_depth or not widget.get_visible():
        return
    if isinstance(widget, Gtk.Label):
        text = widget.get_text().strip()
        if text:
            out.append(text)
    elif isinstance(widget, Gtk.Button):
        # Gtk.Button 内部就是一个 Gtk.Label，避免重复计数
        label = widget.get_label()
        if label and not isinstance(widget.get_first_child(), Gtk.Label):
            out.append(label)
    if isinstance(widget, Gtk.Stack):
        # 只遍历当前显示的页面，否则会把所有页的文字都算进来
        _collect(widget.get_visible_child(), out, depth + 1, max_depth)
        return

    child = widget.get_first_child()
    while child is not None:
        _collect(child, out, depth + 1, max_depth)
        child = child.get_next_sibling()


def widget_texts(root) -> list[str]:
    """按树序返回所有可见文本（用于断言界面确实渲染了内容）。"""
    out: list[str] = []
    if root is None:
        return out
    _collect(root, out)
    return out


def count_widgets(root) -> int:
    """控件总数（判断页面是否有实质结构）。"""
    total = 0
    stack = [root]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        total += 1
        if isinstance(node, Gtk.Stack):
            stack = [node.get_visible_child()]
            continue
        child = node.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return total
