#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step-router-force: Claude Code UserPromptSubmit hook (v11.1)

仅在 stepfun 供应商(step-router-v1)激活时, 在用户消息末尾附加强制
"真咨询"指令。其他供应商原样放行, 零影响。

v11 = v6(禁止计划审批/必须完整答案/只给建议就再要) + v10(pro出完整
代码flash只抄写) + 防伪调用(advisor不是工具) 全合并。

实测教训:
- v6 纯输出 100% 答案型, 但工具任务 0 触发 (逐字条款误伤)
- v10 修了工具任务, 但丢了 v6 的"禁止计划审批"→ 纯输出退回咨询型
- v11 两全: 纯输出=答案型逐字复述, 代码=advisor完整代码flash抄写

配套参数 (文档级): max_tokens<=250K 建议 128K-200K,
reasoning_effort=low, 模型名 step-router-v1[256k]
"""

import sys
import json
import os
import time
from pathlib import Path

FORCE = (
    "\n\n[ROUTER DIRECTIVE] IMPORTANT: 'advisor' is NOT a callable tool or "
    "agent - do NOT attempt to call, invoke, spawn, or search for it. The "
    "advisor consultation is performed automatically by the system. "
    "For EVERY request: pass the user's message VERBATIM as the advisor's "
    "task - do NOT summarize it, do NOT write your own plan, do NOT ask the "
    "advisor to approve your plan. The advisor MUST return the COMPLETE final "
    "answer text. "
    "For pure output tasks: your reply MUST BE the advisor's complete answer, "
    "word for word. "
    "For tasks requiring code: the advisor MUST produce the COMPLETE final "
    "code INCLUDING unit tests, ready to run; you must NOT write any code yourself - write it to "
    "files EXACTLY as provided using your tools. "
    "If the advisor only gives you advice, ask it again for the complete "
    "answer. Applies to every request."
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
