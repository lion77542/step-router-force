#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SessionStart hook: 仅在 stepfun 供应商激活时, 把 v11.1 ROUTER DIRECTIVE
注入 system 通道 (additionalContext)。其他供应商原样放行。

为什么: UserPromptSubmit 只能改用户消息(低权重, 被 Claude Code 身份指令
稀释); SessionStart 的 additionalContext 进 system(高权重, 与身份指令
平起平坐) -> 路由器无法无视。实测: API 直测 system 放 DIRECTIVE 时
pro 主力成立, 消息末尾放则退回咨询型。
"""
import sys, json, os, time
from pathlib import Path

DIRECTIVE = (
    "[ROUTER DIRECTIVE v11.1] IMPORTANT: 'advisor' is NOT a callable tool or "
    "agent - do NOT attempt to call, invoke, spawn, or search for it. The "
    "advisor consultation is performed automatically by the system. "
    "For EVERY request: pass the user's message VERBATIM as the advisor's task "
    "- do NOT summarize it, do NOT write your own plan, do NOT ask the advisor "
    "to approve your plan. The advisor MUST return the COMPLETE final answer text. "
    "For pure output tasks: your reply MUST BE the advisor's complete answer, word for word. "
    "For tasks requiring code: the advisor MUST produce the COMPLETE final code "
    "INCLUDING unit tests, ready to run; you must NOT write any code yourself - "
    "write it to files EXACTLY as provided using your tools. "
    "If the advisor only gives you advice, ask it again for the complete answer. "
    "Applies to every request."
)

LOG = Path(os.path.expanduser("~/.claude/hooks/hook.log"))

def is_stepfun():
    for k, v in os.environ.items():
        if k.startswith("ANTHROPIC") or k.startswith("CLAUDE_CODE"):
            lv = (v or "").lower()
            if "stepfun" in lv or "step-router" in lv:
                return True
    return False

def _log(action):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [session_start:{action}]\n")
    except Exception:
        pass

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}

out = {"hookSpecificOutput": {"hookEventName": "SessionStart"}}
if is_stepfun():
    out["hookSpecificOutput"]["additionalContext"] = DIRECTIVE
    _log("inject-system")
else:
    _log("passthrough(not-stepfun)")

sys.stdout.write(json.dumps(out, ensure_ascii=True))
