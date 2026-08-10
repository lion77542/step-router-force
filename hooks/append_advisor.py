#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step-router-force: Claude Code UserPromptSubmit hook (v7)

仅在 stepfun 供应商(step-router-v1)激活时, 在用户消息末尾附加强制
"真咨询"指令。其他供应商原样放行, 零影响。

v7 指令 (最终版):
- 纯输出任务: advisor 出完整答案, 逐字采用
- 工具/代码任务: 先 advisor 完整方案, 再用工具执行 (关键: 逐字约束
  只对纯输出, 否则路由器判定"要调工具没法逐字"而放弃 advisor -
  实测 v6 纯逐字版工具任务 0 触发)

配套参数:
- max_tokens >= 60000, 否则 reasoning_content 思考吃光额度
- 默认 temperature 即可 (实测 3/3 advisor+tool_calls)

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
    try:
        data = json.load(sys.stdin)
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

    _log(action)

    sys.stdout.write(json.dumps(data, ensure_ascii=True))


if __name__ == "__main__":
    main()
