import re
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

class PathFixerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.scope.get("path")
        if path:
            # Collapse multiple /api into a single /api
            # This regex looks for two or more occurrences of '/api' at the start of the path
            # and replaces them with a single '/api'
            new_path = re.sub(r'^(/api)+', '/api', path)
            if new_path != path:
                request.scope["path"] = new_path
        
        response = await call_next(request)
        return response
