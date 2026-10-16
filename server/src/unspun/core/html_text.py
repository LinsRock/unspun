"""Bounded visible-text extraction; stored paragraphs never contain markup."""

import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser

_SKIP = {
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "iframe",
}
_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_BLOCK = {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "blockquote"}


@dataclass
class TextNode:
    tag: str
    attrs: dict[str, str]
    excluded: bool = False
    children: list["TextNode | str"] = field(default_factory=lambda: list["TextNode | str"]())

    def text(self) -> str:
        style = re.sub(r"\s+", "", self.attrs.get("style", "").lower())
        if (
            self.excluded
            or self.tag in _SKIP
            or "hidden" in self.attrs
            or self.attrs.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        ):
            return ""
        text = "".join(value if isinstance(value, str) else value.text() for value in self.children)
        return "\n" + text + "\n" if self.tag in _BLOCK else text

    def markup(self) -> str:
        if self.excluded:
            return ""
        contents = "".join(
            escape(value) if isinstance(value, str) else value.markup() for value in self.children
        )
        if self.tag == "root":
            return contents
        attributes = "".join(
            " " + key + '="' + escape(value, quote=True) + '"'
            for key, value in self.attrs.items()
            if key in {"id", "class", "href"}
        )
        return (
            "<"
            + self.tag
            + attributes
            + ">"
            + (contents + "</" + self.tag + ">" if self.tag not in _VOID else "")
        )


class TextPage(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        if len(html.encode()) > 2 * 1024 * 1024:
            raise ValueError("HTML exceeds material input bound")
        self.root = TextNode("root", {})
        self.nodes = [self.root]
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.nodes) >= 50000 or len(self.stack) >= 256:
            raise ValueError("HTML structure exceeds material bound")
        node = TextNode(tag, {key: value or "" for key, value in attrs})
        style = re.sub(r"\s+", "", node.attrs.get("style", "").lower())
        node.excluded = (
            self.stack[-1].excluded
            or tag in _SKIP
            or "hidden" in node.attrs
            or node.attrs.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
            or bool(
                set(node.attrs.get("class", "").split())
                & {"hidden", "d-none", "sr-only", "visually-hidden"}
            )
        )
        self.nodes.append(node)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)

    def by_id(self, value: str) -> TextNode | None:
        return next(
            (node for node in self.nodes if node.attrs.get("id") == value and not node.excluded),
            None,
        )

    def by_class(self, value: str) -> TextNode | None:
        return next(
            (
                node
                for node in self.nodes
                if value in node.attrs.get("class", "").split() and not node.excluded
            ),
            None,
        )

    def meta(self, key: str) -> str | None:
        return next(
            (
                node.attrs.get("content")
                for node in self.nodes
                if not node.excluded
                and node.tag == "meta"
                and (node.attrs.get("name") or node.attrs.get("property", "")).lower()
                == key.lower()
            ),
            None,
        )


def paragraphs(text: str) -> list[str]:
    result: list[str] = []
    for line in text.splitlines():
        value = " ".join(line.split())
        if value and value not in result:
            result.extend(value[index : index + 20000] for index in range(0, len(value), 20000))
    return result


def visible_text(html: str) -> str:
    return "\n".join(paragraphs(TextPage(html).root.text()))
