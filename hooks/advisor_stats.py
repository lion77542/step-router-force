#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step-router-force: advisor 命中率统计

统计 Claude Code 会话记录中 step-router-v1 的 advisor(deepseek-v4-pro)
调用情况。命中 = 响应中出现 [Advisor consultation 块。

用法:
    python advisor_stats.py                      # 扫描当前项目目录的会话
    python advisor_stats.py <目录或文件>          # 指定范围
"""

import json
import sys
import os
from pathlib import Path


def sanitize(cwd):
    return cwd.replace(chr(92), "-").replace(":", "-")


def analyze(path):
    """返回 (advisor块数, 助手轮次) 或 None(不可读/无效)"""
    advisor, turns = 0, 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                msg = entry.get("message", {}) or {}
                if msg.get("role") == "assistant" and isinstance(msg.get("content"), list):
                    turns += 1
                    text = json.dumps(msg.get("content", ""), ensure_ascii=False)
                    if "[Advisor consultation" in text:
                        advisor += 1
    except Exception:
        return None
    return advisor, turns


def main():
    targets = sys.argv[1:] or [
        os.path.expanduser(f"~/.claude/projects/{sanitize(os.getcwd())}")
    ]
    total_a, total_t = 0, 0
    for target in targets:
        p = Path(target)
        files = sorted(p.rglob("*.jsonl")) if p.is_dir() else [p]
        for fp in files:
            result = analyze(fp)
            if not result:
                continue
            a, n = result
            if n == 0:
                continue
            total_a += a
            total_t += n
            rate = f"{a / n * 100:.0f}%"
            print(f"  {fp.parent.name[:12]:14s} | advisor {a:4d} / 轮 {n:4d} | {rate}")
    if total_t:
        print(f"\n汇总: advisor {total_a} / 总轮 {total_t} = {total_a / total_t * 100:.0f}%")
        print("(命中 = 响应里出现 [Advisor consultation 块 = deepseek-v4-pro 被咨询)")
    else:
        print("未找到可分析的会话记录")


if __name__ == "__main__":
    main()
