"""
Generic tool-calling framework shared by every agent stage: the OpenAI/Groq
JSON schema a tool exposes to the model, the Python implementation behind it,
and the execution trace recorded for observability - all in one place so
they can't drift apart. No stage calls a tool function directly; everything
goes through ToolRegistry.execute(), so every call is timed and traced the
same way regardless of which agent is making it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolCallRecord:
    """One traced invocation of one tool - the unit of agent observability."""
    tool: str
    args: dict
    result: Any
    ok: bool
    duration_ms: float
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
            "ok": self.ok,
            "duration_ms": round(self.duration_ms, 1),
            "error": self.error,
        }


@dataclass
class AgentTrace:
    """Accumulates ToolCallRecords across one agent run (one tool-calling
    loop), so the pipeline's output can show exactly what the agent did and
    how long each step took - not just its final answer."""
    calls: list[ToolCallRecord] = field(default_factory=list)

    def record(self, call: ToolCallRecord) -> None:
        self.calls.append(call)

    def to_list(self) -> list[dict]:
        return [c.to_dict() for c in self.calls]

    @property
    def total_duration_ms(self) -> float:
        return sum(c.duration_ms for c in self.calls)

    @property
    def failure_count(self) -> int:
        return sum(1 for c in self.calls if not c.ok)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., dict]

    def schema(self) -> dict:
        """OpenAI/Groq-compatible function-calling schema."""
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }

    def run(self, args: dict, trace: Optional[AgentTrace] = None) -> dict:
        start = time.perf_counter()
        try:
            result = self.fn(**args)
            ok = not (isinstance(result, dict) and result.get("error"))
            error = result.get("error") if isinstance(result, dict) and not ok else None
        except Exception as e:
            result = {"error": str(e)}
            ok = False
            error = f"{type(e).__name__}: {e}"
        duration_ms = (time.perf_counter() - start) * 1000

        if trace is not None:
            trace.record(ToolCallRecord(tool=self.name, args=args, result=result, ok=ok, duration_ms=duration_ms, error=error))
        return result


class ToolRegistry:
    """Tools register themselves here via @registry.tool(...). This is the
    only thing a Groq tool-calling loop needs: .schemas() for the request,
    .execute() to route every tool_call the model makes."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def tool(self, name: str, description: str, parameters: dict):
        def decorator(fn: Callable[..., dict]) -> Callable[..., dict]:
            self._tools[name] = Tool(name=name, description=description, parameters=parameters, fn=fn)
            return fn
        return decorator

    def schemas(self, names: Optional[list[str]] = None) -> list[dict]:
        tools = self._tools.values() if names is None else (self._tools[n] for n in names)
        return [t.schema() for t in tools]

    def execute(self, name: str, args: dict, trace: Optional[AgentTrace] = None) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            result = {"error": f"unknown tool {name}"}
            if trace is not None:
                trace.record(ToolCallRecord(tool=name, args=args, result=result, ok=False, duration_ms=0.0, error=result["error"]))
            return result
        return tool.run(args, trace=trace)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
