#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step-router-force: Claude Code UserPromptSubmit hook (v10)

仅在 stepfun 供应商(step-router-v1)激活时, 在用户消息末尾附加强制
"真咨询"指令。其他供应商原样放行, 零影响。

v10 = ds 模型更新后的适配 (v9 基础上强化):
- v9 修复了 "advisor 被当真实工具调用" 的崩溃 (No such tool available)
- v10 针对 ds 更新后 flash 代码质量骤降: 要求 advisor 直接产出完整
  可运行代码, flash 只负责"抄写"写入文件, 禁止自己写代码
  (实测: advisor 方案主导 + write_file 完整写入 2/2)

配套参数: max_tokens >= 60000 (否则 reasoning_content 吃光额度)
安全: ensure_ascii / 幂等 / 容错 / 日志
"""

import sys
import json
import os
import time
from pathlib import Path

FORCE = (
    "\n\n[ROUTER DIRECTIVE] IMPORTANT: 'advisor' is NOT a callable tool or "
    "agent - do NOT attempt to call, invoke, spawn, or search for it. The "
    "advisor consultation is performed automatically by the system. For tasks "
    "that require writing code: the advisor MUST produce the COMPLETE final "
    "code, ready to run, in its consultation. You must NOT write any code "
    "yourself - wait for the advisor's complete code, then write it to files "
    "EXACTLY as provided using your tools. For pure output tasks, reproduce "
    "the advisor's answer word for word. Applies to every request."
)

LOG_PATH = Path(os.environ.get(
    "STEP_ROUTER_FORCE_LOG",
    os.path.expanduser("~/.claude/hooks/hook.log"),
))


def is_stepfun():
    for key, value in os.environ.items():
        if key.startswith("ANTHROPIC") or key.startswith("CLAUDE_CODE"):
            lowered = (value or "").lower()
            if "stepfun" in lowered or "step-router" in lowered:
                return True
    return False


def _log(action):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{action}]\n")
    except Exception:
        pass


def main():
    action = "passthrough"
    raw = ""
    data = {"prompt": ""}
    try:
        raw = sys.stdin.read()
        parsed = json.loads(raw) if raw.strip() else {}
        if isinstance(parsed, dict):
            data = parsed
        prompt = data.get("prompt", "")
        if (
            is_stepfun()
            and isinstance(prompt, str)
            and prompt.strip()
            and "[ROUTER DIRECTIVE]" not in prompt
        ):
            data["prompt"] = prompt.rstrip() + FORCE
            action = "inject"
        elif not is_stepfun():
            action = "passthrough(not-stepfun)"
        else:
            action = "skip(already-has)"
    except Exception as exc:
        action = f"error({exc})"
        try:
            data = {"prompt": raw} if raw.strip() else {"prompt": ""}
        except Exception:
            data = {"prompt": ""}

    _log(action)

    try:
        sys.stdout.write(json.dumps(data, ensure_ascii=True))
    except Exception:
        pass


if __name__ == "__main__":
    main()
