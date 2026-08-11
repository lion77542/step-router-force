#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step-router-force: Claude Code UserPromptSubmit hook (v8)

仅在 stepfun 供应商(step-router-v1)激活时, 在用户消息末尾附加强制
"真咨询"指令。其他供应商原样放行, 零影响。

v8 = v7 + 健壮性修复:
- 修复 v1-v7 潜伏 bug: json.load 失败时 data 未定义 → json.dumps 抛
  NameError → hook 崩溃 (实测触发: 粘贴超长文本时解析失败)
- 解析失败时回传原文, 绝不清空用户消息
- stdout 写入也包 try, 任何异常都不让 hook 崩

v7 指令 (最终版):
- 纯输出任务: advisor 出完整答案, 逐字采用
- 工具/代码任务: 先 advisor 完整方案, 再用工具执行

配套参数: max_tokens >= 60000 (否则 reasoning_content 吃光额度)
安全: ensure_ascii / 幂等 / 容错 / 日志
"""

import sys
import json
import os
import time
from pathlib import Path

FORCE = (
    "\n\n[ROUTER DIRECTIVE] Before answering, you MUST consult the advisor. "
    "CRITICAL: pass the user's message VERBATIM as the advisor's task - do NOT "
    "summarize it, do NOT write your own plan, do NOT ask the advisor to approve "
    "your plan. The advisor must return the COMPLETE final answer text. "
    "Your reply MUST BE the advisor's complete answer, word for word. "
    "If the task requires writing code or files, first get the advisor's complete "
    "solution, then write the files using your tools."
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
        # 解析失败时回传原文, 绝不清空用户消息
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
