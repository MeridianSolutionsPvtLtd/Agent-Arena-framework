from typing import Any, Dict, List

class ToolRegistry:
    """A simple registry to hold all tools available to the Planner and Agents."""
    
    def __init__(self):
        self._tools = {}
        self._metadata = {}
        
    def register(self, tool_func: Any, metadata: Dict[str, Any] = None):
        """Registers a tool using its __name__ or provided tool name from Langchain."""
        # Handle Langchain @tool instances which have .name
        name = getattr(tool_func, "name", None) or tool_func.__name__
        self._tools[name] = tool_func
        self._metadata[name] = metadata or {}
        
    def get_tool(self, name: str) -> Any:
        return self._tools.get(name)

    def get_tool_metadata(self, name: str) -> Dict[str, Any]:
        return self._metadata.get(name, {})
        
    def get_all_metadata(self) -> List[Any]:
        # Return simple objects that mimic what planner.py expects
        class ToolMetadata:
            def __init__(self, t_id, name, desc):
                self.id = t_id
                self.name = name
                self.description = desc
                
        meta = []
        for name, t in self._tools.items():
            desc = getattr(t, "description", t.__doc__)
            meta.append(ToolMetadata(t_id=name, name=name, desc=desc))
        return meta

# Global singleton
registry = ToolRegistry()
