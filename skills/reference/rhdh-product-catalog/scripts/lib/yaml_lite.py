#!/usr/bin/env python3
"""Minimal YAML parser for overlay Package and Plugin metadata (stdlib only).

Adapted from the rhdh-local fetch-plugin-metadata parser. Handles the subset
used in workspaces/*/metadata/*.yaml: scalars, nested maps, lists of maps,
quoted strings, comments, and ``---`` document markers.

Does not handle anchors, merge keys, tags, or flow collections beyond
empty ``[]`` / ``{}``.
"""

from __future__ import annotations

from typing import Any


def parse_yaml(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    return _parse_mapping(lines, 0, 0)[0]


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def _strip_quotes(val: str) -> str:
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return val[1:-1]
    return val


def _strip_inline_comment(val: str) -> str:
    in_single = False
    in_double = False
    prev_space = False
    for i, ch in enumerate(val):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double and prev_space:
            return val[:i].rstrip()
        prev_space = ch == " "
    return val


def _scalar(val: str) -> Any:
    v = _strip_inline_comment(val).strip()
    if v in ("true", "True", "yes"):
        return True
    if v in ("false", "False", "no"):
        return False
    if v in ("null", "~", ""):
        return None
    if v == "[]":
        return []
    if v == "{}":
        return {}
    # Keep dotted versions as strings (1.52.0, 0.9.1).
    if v.count(".") >= 2:
        return _strip_quotes(v)
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return _strip_quotes(v)


def _parse_mapping(lines: list[str], idx: int, base_indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}

    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            idx += 1
            continue

        cur_indent = _indent_of(line)
        if cur_indent < base_indent:
            break
        if cur_indent > base_indent:
            idx += 1
            continue
        if stripped.startswith("- "):
            idx += 1
            continue

        colon_pos = stripped.find(":")
        if colon_pos == -1:
            idx += 1
            continue

        key = stripped[:colon_pos].strip()
        after_colon = stripped[colon_pos + 1 :].strip()

        if after_colon and not after_colon.startswith("#"):
            result[key] = _scalar(after_colon)
            idx += 1
        else:
            child_indent = None
            peek = idx + 1
            while peek < len(lines):
                pl = lines[peek]
                ps = pl.strip()
                if ps and not ps.startswith("#") and ps != "---":
                    child_indent = _indent_of(pl)
                    break
                peek += 1

            if child_indent is None or child_indent <= cur_indent:
                result[key] = None
                idx += 1
            elif lines[peek].strip().startswith("- "):
                result[key], idx = _parse_list(lines, peek, child_indent)
            else:
                first_child = lines[peek].strip()
                if ":" in first_child:
                    result[key], idx = _parse_mapping(lines, peek, child_indent)
                else:
                    block_lines: list[str] = []
                    bi = peek
                    while bi < len(lines):
                        bl = lines[bi]
                        bs = bl.strip()
                        if not bs or bs.startswith("#"):
                            block_lines.append("")
                            bi += 1
                            continue
                        if _indent_of(bl) < child_indent:
                            break
                        block_lines.append(bl.strip())
                        bi += 1
                    while block_lines and not block_lines[-1]:
                        block_lines.pop()
                    result[key] = "\n".join(block_lines)
                    idx = bi

    return result, idx


def _parse_list(lines: list[str], idx: int, base_indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []

    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            idx += 1
            continue

        cur_indent = _indent_of(line)
        if cur_indent < base_indent:
            break
        if cur_indent > base_indent:
            idx += 1
            continue
        if not stripped.startswith("- "):
            break

        item_text = stripped[2:].strip()
        if ":" in item_text:
            colon_pos = item_text.find(":")
            first_key = item_text[:colon_pos].strip()
            first_val_str = item_text[colon_pos + 1 :].strip()
            item_dict: dict[str, Any] = {}
            item_indent = cur_indent + 2

            if first_val_str and not first_val_str.startswith("#"):
                item_dict[first_key] = _scalar(first_val_str)
                idx += 1
            else:
                peek = idx + 1
                child_indent = None
                while peek < len(lines):
                    pl = lines[peek]
                    ps = pl.strip()
                    if ps and not ps.startswith("#") and ps != "---":
                        child_indent = _indent_of(pl)
                        break
                    peek += 1

                if child_indent is not None and child_indent > item_indent:
                    if lines[peek].strip().startswith("- "):
                        item_dict[first_key], idx = _parse_list(lines, peek, child_indent)
                    else:
                        first_child = lines[peek].strip()
                        if ":" in first_child:
                            item_dict[first_key], idx = _parse_mapping(
                                lines, peek, child_indent
                            )
                        else:
                            item_dict[first_key] = _scalar(first_child)
                            idx = peek + 1
                else:
                    item_dict[first_key] = None
                    idx += 1

            rest, idx = _parse_mapping(lines, idx, item_indent)
            item_dict.update(rest)
            result.append(item_dict)
        else:
            result.append(_scalar(item_text))
            idx += 1

    return result, idx
