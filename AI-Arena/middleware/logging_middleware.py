import time
import uuid
import jwt
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from utils.logger import get_logger, request_id_ctx, user_id_ctx
from config import settings

logger = get_logger("middleware")

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Generate Request ID
        request_id = str(uuid.uuid4())
        request_id_ctx.set(request_id)
        
        # Extract User ID
        user_id = "unauthenticated"
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                # Optimistic decoding
                payload = jwt.decode(token, options={"verify_signature": False})
                if "sub" in payload:
                    user_id = payload["sub"]
            except Exception:
                pass 
        
        user_id_ctx.set(user_id)
        
        # Log Request Start
        logger.info(
            f"Incoming request: {request.method} {request.url.path}",
            extra={"status_code": 0} 
        )

        try:
            response = await call_next(request)
            
            # Log Request specific info
            extra = {
                "status_code": response.status_code,
            }
            logger.info(
                f"Request completed: {request.method} {request.url.path} - Time: {time.time() - start_time:.4f}s",
                extra=extra
            )
            return response
            
        except Exception as e:
            logger.error(
                f"Request failed: {str(e)}",
                exc_info=True,
                extra={"status_code": 500}
            )
            raise e
