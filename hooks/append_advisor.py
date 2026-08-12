#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step-router-force: Claude Code UserPromptSubmit hook (v9)

仅在 stepfun 供应商(step-router-v1)激活时, 在用户消息末尾附加强制
"真咨询"指令。其他供应商原样放行, 零影响。

v9 = 修复 v7/v8 重大缺陷: 指令里 "call the advisor function" 诱导
executor 把 advisor 当真实工具调用 → "No such tool available: advisor"
报错 → 放弃咨询 → flash 独自写代码(实测 bug 频出)。

v9 关键修正:
- 明确 "advisor 不是可调用工具, 不要调用/搜索/派生它, 会失败"
- 咨询是系统自动完成的: executor 只需在回复中显式请求咨询,
  系统会在下一轮返回 advisor 指引; 未返回则再请求一次
- 收到指引前不写最终答案; 指引到达后: 纯输出任务逐字复述,
  工具/代码任务先拿完整方案再执行

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
    "agent - do NOT attempt to call, invoke, spawn, or search for it; any such "
    "attempt will fail. The advisor consultation is performed automatically by "
    "the system. Before answering every request: explicitly request the advisor "
    "consultation in your response text, and do not produce the final answer "
    "until the system has returned the advisor's guidance (if it is not "
    "returned, request it once more). Base your final answer on the advisor's "
    "complete guidance: for pure output tasks reproduce it word for word; for "
    "tasks requiring tools or code, first obtain the advisor's complete "
    "solution, then execute it with your tools. Applies to every request."
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
