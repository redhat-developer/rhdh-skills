#!/usr/bin/env python3
"""Convert Jira wiki markup (template subset) to Atlassian Document Format JSON.

Handles: headings (hN.), paragraphs, bullet lists (* item), ordered lists (# item),
         task items ((?) TODO, (/) DONE), bold (*text*), italic (_text_),
         monospace ({{text}} and `backtick`).

Usage:
    python scripts/jira-wiki-to-adf.py <input.txt>              # stdout
    python scripts/jira-wiki-to-adf.py <input.txt> <output.json>  # file
"""

import json
import re


def parse_inline(text):
    """Parse Jira wiki inline marks into ADF text nodes.

    Order matters: bold (*text*) is matched before bare asterisks,
    monospace before backticks.
    """
    nodes = []
    pattern = re.compile(r"\*([^*\n]+)\*|_([^_\n]+)_|\{\{([^}]+)\}\}|`([^`\n]+)`")
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            nodes.append({"type": "text", "text": text[last : m.start()]})
        if m.group(1) is not None:  # *bold*
            nodes.append({"type": "text", "text": m.group(1), "marks": [{"type": "strong"}]})
        elif m.group(2) is not None:  # _italic_
            nodes.append({"type": "text", "text": m.group(2), "marks": [{"type": "em"}]})
        elif m.group(3) is not None:  # {{monospace}}
            nodes.append({"type": "text", "text": m.group(3), "marks": [{"type": "code"}]})
        else:  # `backtick`
            nodes.append({"type": "text", "text": m.group(4), "marks": [{"type": "code"}]})
        last = m.end()
    if last < len(text):
        nodes.append({"type": "text", "text": text[last:]})
    return nodes or [{"type": "text", "text": ""}]


def _para(text):
    return {"type": "paragraph", "content": parse_inline(text)}


def _heading(level, text):
    return {"type": "heading", "attrs": {"level": level}, "content": parse_inline(text)}


def _task_list(items, idx):
    return {
        "type": "taskList",
        "attrs": {"localId": f"tl-{idx}"},
        "content": [
            {
                "type": "taskItem",
                "attrs": {"localId": f"ti-{idx}-{i}", "state": "DONE" if checked else "TODO"},
                "content": parse_inline(text),
            }
            for i, (checked, text) in enumerate(items)
        ],
    }


def _bullet_list(items):
    return {
        "type": "bulletList",
        "content": [{"type": "listItem", "content": [_para(item)]} for item in items],
    }


def _ordered_list(items):
    return {
        "type": "orderedList",
        "content": [{"type": "listItem", "content": [_para(item)]} for item in items],
    }


# hN. text  (heading)
HEADING_RE = re.compile(r"^h([1-6])\.\s+(.*)")
# (?) text  (task item, unchecked)
TASK_TODO_RE = re.compile(r"^\(\?\)\s+(.*)")
# (/) text  (task item, checked)
TASK_DONE_RE = re.compile(r"^\(/\)\s+(.*)")
# * text  (bullet — asterisk + whitespace; does NOT match *bold*)
BULLET_RE = re.compile(r"^\*\s+(.*)")
# # text or  # text  (ordered list — optional leading whitespace)
ORDERED_RE = re.compile(r"^\s*#\s+(.*)")


def convert(wiki):
    lines = wiki.splitlines()
    content = []
    tl_idx = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if not s:
            i += 1
            continue

        # Heading
        m = HEADING_RE.match(s)
        if m:
            content.append(_heading(int(m.group(1)), m.group(2).strip()))
            i += 1
            continue

        # Task items — collect consecutive (?) and (/) lines into one taskList
        if TASK_TODO_RE.match(s) or TASK_DONE_RE.match(s):
            items = []
            while i < len(lines):
                s2 = lines[i].strip()
                mt = TASK_TODO_RE.match(s2)
                md = TASK_DONE_RE.match(s2)
                if mt:
                    items.append((False, mt.group(1)))
                    i += 1
                elif md:
                    items.append((True, md.group(1)))
                    i += 1
                else:
                    break
            content.append(_task_list(items, tl_idx))
            tl_idx += 1
            continue

        # Bullet list (* item — requires space after *, so *bold* is not matched)
        m = BULLET_RE.match(s)
        if m:
            items = []
            while i < len(lines):
                bm = BULLET_RE.match(lines[i].strip())
                if bm:
                    items.append(bm.group(1))
                    i += 1
                else:
                    break
            if items:
                content.append(_bullet_list(items))
            continue

        # Ordered list (# item or  # item with leading whitespace)
        m = ORDERED_RE.match(line)
        if m:
            items = []
            while i < len(lines):
                om = ORDERED_RE.match(lines[i])
                if om:
                    items.append(om.group(1))
                    i += 1
                else:
                    break
            if items:
                content.append(_ordered_list(items))
            continue

        # Paragraph — collect consecutive non-special lines
        para_lines = []
        while i < len(lines):
            s2 = lines[i].strip()
            raw = lines[i]
            if not s2:
                break
            if HEADING_RE.match(s2):
                break
            if TASK_TODO_RE.match(s2) or TASK_DONE_RE.match(s2):
                break
            if BULLET_RE.match(s2):
                break
            if ORDERED_RE.match(raw):
                break
            para_lines.append(s2)
            i += 1
        if para_lines:
            content.append(_para(" ".join(para_lines)))

    return {"version": 1, "type": "doc", "content": content}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert Jira wiki markup to Atlassian Document Format (ADF) JSON."
    )
    parser.add_argument("input", help="Input file containing Jira wiki markup")
    parser.add_argument("output", nargs="?", help="Output JSON file (default: stdout)")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        wiki = f.read()

    result = json.dumps(convert(wiki), ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
    else:
        print(result)
