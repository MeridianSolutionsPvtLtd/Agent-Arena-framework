class TraceManager:
    """Thread-safe registry for real-time execution tracing."""
    _listeners = {}

    @classmethod
    def register(cls, trace_id: str, callback):
        cls._listeners[trace_id] = callback

    @classmethod
    def unregister(cls, trace_id: str):
        cls._listeners.pop(trace_id, None)

    @classmethod
    def emit(cls, trace_id: str, data: dict):
        if trace_id and trace_id in cls._listeners:
            try:
                cls._listeners[trace_id](data)
            except Exception:
                pass
