# -*- coding: utf-8 -*-
"""Швидка звірка фактичного стану Feria-Sim проти AGENTS.md і docs/AI_CONTEXT.md."""
import ast
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    from feria_sim import engine as E

    web_src = open(os.path.join(ROOT, "feria_sim", "web.py"), encoding="utf-8").read()
    cli_src = open(os.path.join(ROOT, "feria_sim", "cli.py"), encoding="utf-8").read()
    test_src = open(os.path.join(ROOT, "tests", "test_feria_sim.py"), encoding="utf-8").read()
    ctx_src = open(os.path.join(ROOT, "docs", "AI_CONTEXT.md"), encoding="utf-8").read()

    get_routes = sorted(set(re.findall(r'u\.path\s*(?:==\s*"([^"]+)"|in\s*\(([^)]+)\))', web_src)))
    flat_get = []
    for a, b in get_routes:
        if a:
            flat_get.append(a)
        if b:
            flat_get.extend(re.findall(r'"([^"]+)"', b))
    flat_get = sorted(set(flat_get))
    post_routes = sorted(set(re.findall(r'path\s*==\s*"(/api/[^"]+)"', web_src)))
    cli_cmds = sorted(set(re.findall(r'sp\.add_parser\("([^"]+)"', cli_src)))

    tree = ast.parse(test_src)
    tests = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            tests.extend(m.name for m in node.body if isinstance(m, ast.FunctionDef) and m.name.startswith("test_"))

    head = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    print(f"HEAD: {head}")
    print(f"CONFIG_DEFAULTS ({len(E.CONFIG_DEFAULTS)}): {', '.join(sorted(E.CONFIG_DEFAULTS))}")
    print(f"GET routes ({len(flat_get)}): {', '.join(flat_get)}")
    print(f"POST routes ({len(post_routes)}): {', '.join(post_routes)}")
    print(f"CLI commands ({len(cli_cmds)}): {', '.join(cli_cmds)}")
    print(f"Tests ({len(tests)})")

    missing = []
    for ep in flat_get + post_routes:
        if ep != "/" and ep not in ctx_src:
            missing.append(f"API route missing in AI_CONTEXT.md: {ep}")
    for cmd in cli_cmds:
        if f"`{cmd}" not in ctx_src:
            missing.append(f"CLI cmd missing in AI_CONTEXT.md: {cmd}")
    for k in E.CONFIG_DEFAULTS:
        if k not in ctx_src:
            missing.append(f"Config key missing in AI_CONTEXT.md: {k}")
    if str(len(tests)) not in ctx_src:
        missing.append(f"Test count {len(tests)} does not match AI_CONTEXT.md")

    if missing:
        print("\n[OUT OF SYNC]")
        for m in missing:
            print(" -", m)
        sys.exit(1)
    print("\n[OK] docs/AI_CONTEXT.md is synchronized.")


if __name__ == "__main__":
    main()
