from functools import lru_cache

from .base import ToolDefinition


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool registration for '{tool.name}'.")
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> ToolDefinition | None:
        return self._tools.get(tool_name)

    def all(self) -> list[ToolDefinition]:
        return list(self._tools.values())


@lru_cache(maxsize=1)
def get_default_registry() -> ToolRegistry:
    registry = ToolRegistry()

    from tasks.assistant_tools import get_tools as get_task_tools

    for tool in get_task_tools():
        registry.register(tool)

    return registry
