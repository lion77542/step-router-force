#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smoke_test: 对本代理发 CC Switch 风格 OpenAI 请求, 验证:
1) 不 400 (convert 不崩)
2) advisor 触发 (答案型)
3) 响应是 OpenAI 格式
4) 流式 SSE 透传正常

用法: python smoke_test.py [http://127.0.0.1:18731]
"""

import json
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18731"


def task():
    return {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system",
             "content": "You are Claude Code, an agent that uses tools to write code."},
            {"role": "user",
             "content": "写一个 Python 线程安全 LRU 缓存类, 含 TTL 支持, 并给出单元测试。用 Bash 运行测试。"},
        ],
        "tools": [
            {"type": "function", "function": {
                "name": "Write", "description": "写文件",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
            {"type": "function", "function": {
                "name": "Bash", "description": "执行命令",
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
        ],
        "tool_choice": "auto",
        "max_tokens": 387000,
        "stream": False,
    }


def main():
    # 1) 非流式 (崩溃复现请求形状)
    t0 = time.time()
    r = requests.post(BASE + "/chat/completions", json=task(), timeout=600)
    print("status:", r.status_code, "(%.1fs)" % (time.time() - t0))
    if r.status_code != 200:
        print(r.text[:800])
        return 1
    d = r.json()
    try:
        m = d['choices'][0]['message']
        reason = d['choices'][0].get('finish_reason')
    except Exception:
        print("响应不是 OpenAI 格式:", json.dumps(d, ensure_ascii=False)[:500])
        return 1
    content = m.get('content') or ''
    tcs = m.get('tool_calls') or []
    print("finish:", reason)
    print("advisor 触发:", 'advisor' in content.lower())
    print("content 长度:", len(content), "字")
    print("tool_calls:", len(tcs))
    for i, tc in enumerate(tcs):
        fn = tc.get('function') or {}
        try:
            args = json.loads(fn.get('arguments') or '{}')
        except Exception:
            args = {}
        print("  [%d] %s -> %s" % (i, fn.get('name'),
                                   json.dumps(args, ensure_ascii=False)[:120]))
    if content:
        print("--- content 开头 400 字 ---")
        print(content[:400])
    # 2) 流式 SSE 透传
    t = requests.post(BASE + "/chat/completions", json=dict(task(), stream=True),
                      timeout=600, stream=True)
    n = 0
    last = b''
    for line in t.iter_lines():
        if line and line.startswith(b'data:'):
            n += 1
            last = line
    print("stream: status=%s SSE data 行数=%s 最后=%s" % (t.status_code, n, last[:120]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
