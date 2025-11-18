# middleware.py - Middleware для LOKAL Cloud
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from typing import Callable
import time
import logging
import json
from datetime import datetime
import traceback

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware для логирования всех HTTP запросов"""
    
    async def dispatch(self, request: Request, call_next: Callable):
        request_id = str(time.time())
        request.state.request_id = request_id
        
        start_time = time.time()
        
        # Логируем входящий запрос
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"from {request.client.host}"
        )
        
        # Обрабатываем запрос
        response = await call_next(request)
        
        # Логируем ответ
        process_time = time.time() - start_time
        logger.info(
            f"[{request_id}] Completed in {process_time:.3f}s "
            f"with status {response.status_code}"
        )
        
        # Добавляем заголовки
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(process_time)
        
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware для глобальной обработки ошибок"""
    
    async def dispatch(self, request: Request, call_next: Callable):
        try:
            response = await call_next(request)
            return response
        
        except Exception as e:
            # Логируем полную ошибку
            logger.error(
                f"Unhandled exception for {request.method} {request.url.path}: {e}",
                exc_info=True
            )
            
            # В production не показываем детали ошибок
            from config import is_production
            
            if is_production():
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "error": "Internal Server Error",
                        "message": "An unexpected error occurred. Please try again later.",
                        "request_id": getattr(request.state, "request_id", "unknown")
                    }
                )
            else:
                # В development показываем детали для отладки
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "error": type(e).__name__,
                        "message": str(e),
                        "traceback": traceback.format_exc().split('\n'),
                        "request_id": getattr(request.state, "request_id", "unknown")
                    }
                )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware для добавления security заголовков"""
    
    async def dispatch(self, request: Request, call_next: Callable):
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware для rate limiting на уровне IP"""
    
    def __init__(self, app, calls: int = 100, period: int = 60):
        super().__init__(app)
        self.calls = calls  # Количество запросов
        self.period = period  # Период в секундах
        self.clients = {}  # IP -> [(timestamp, count)]
    
    async def dispatch(self, request: Request, call_next: Callable):
        client_ip = request.client.host
        
        # Пропускаем для некоторых endpoints (health check и т.д.)
        if request.url.path in ["/health", "/", "/docs", "/openapi.json"]:
            return await call_next(request)
        
        now = time.time()
        
        # Инициализируем для нового IP
        if client_ip not in self.clients:
            self.clients[client_ip] = []
        
        # Очищаем старые записи
        self.clients[client_ip] = [
            (ts, count) for ts, count in self.clients[client_ip]
            if now - ts < self.period
        ]
        
        # Считаем запросы
        total_requests = sum(count for _, count in self.clients[client_ip])
        
        if total_requests >= self.calls:
            logger.warning(f"Rate limit exceeded for {client_ip}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Too Many Requests",
                    "message": f"Rate limit exceeded. Max {self.calls} requests per {self.period} seconds.",
                    "retry_after": self.period
                },
                headers={"Retry-After": str(self.period)}
            )
        
        # Добавляем текущий запрос
        self.clients[client_ip].append((now, 1))
        
        response = await call_next(request)
        
        # Добавляем rate limit headers
        remaining = self.calls - total_requests - 1
        response.headers["X-RateLimit-Limit"] = str(self.calls)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        response.headers["X-RateLimit-Reset"] = str(int(now + self.period))
        
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware для сбора метрик"""
    
    def __init__(self, app):
        super().__init__(app)
        self.metrics = {
            "total_requests": 0,
            "total_errors": 0,
            "endpoints": {},  # path -> {count, total_time, errors}
            "status_codes": {},  # code -> count
            "start_time": datetime.utcnow()
        }
    
    async def dispatch(self, request: Request, call_next: Callable):
        start_time = time.time()
        
        # Обрабатываем запрос
        response = await call_next(request)
        
        # Собираем метрики
        process_time = time.time() - start_time
        path = request.url.path
        status_code = response.status_code
        
        # Общие метрики
        self.metrics["total_requests"] += 1
        
        if status_code >= 400:
            self.metrics["total_errors"] += 1
        
        # Метрики по endpoint
        if path not in self.metrics["endpoints"]:
            self.metrics["endpoints"][path] = {
                "count": 0,
                "total_time": 0.0,
                "errors": 0
            }
        
        self.metrics["endpoints"][path]["count"] += 1
        self.metrics["endpoints"][path]["total_time"] += process_time
        
        if status_code >= 400:
            self.metrics["endpoints"][path]["errors"] += 1
        
        # Метрики по status code
        self.metrics["status_codes"][status_code] = \
            self.metrics["status_codes"].get(status_code, 0) + 1
        
        return response
    
    def get_metrics(self) -> dict:
        """Получить собранные метрики"""
        uptime = (datetime.utcnow() - self.metrics["start_time"]).total_seconds()
        
        # Вычисляем среднее время ответа по endpoint
        endpoint_stats = {}
        for path, stats in self.metrics["endpoints"].items():
            endpoint_stats[path] = {
                "count": stats["count"],
                "avg_response_time": stats["total_time"] / stats["count"],
                "errors": stats["errors"],
                "error_rate": stats["errors"] / stats["count"] * 100
            }
        
        return {
            "uptime_seconds": uptime,
            "total_requests": self.metrics["total_requests"],
            "total_errors": self.metrics["total_errors"],
            "error_rate": (self.metrics["total_errors"] / max(self.metrics["total_requests"], 1)) * 100,
            "requests_per_second": self.metrics["total_requests"] / uptime,
            "endpoints": endpoint_stats,
            "status_codes": self.metrics["status_codes"]
        }


# Глобальный экземпляр для доступа к метрикам
metrics_middleware = None


def setup_middleware(app):
    """Настройка всех middleware"""
    global metrics_middleware
    from config import settings
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=settings.ALLOW_CREDENTIALS,
        allow_methods=settings.ALLOWED_METHODS,
        allow_headers=settings.ALLOWED_HEADERS,
    )
    
    # Gzip compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    
    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)
    
    # Rate limiting (если включен)
    if settings.RATE_LIMIT_ENABLED:
        app.add_middleware(
            RateLimitMiddleware,
            calls=settings.RATE_LIMIT_MAX_ATTEMPTS * 10,  # Более мягкий лимит на IP
            period=60
        )
    
    # Metrics collection
    if settings.METRICS_ENABLED:
        metrics_middleware = MetricsMiddleware(app)
        app.add_middleware(MetricsMiddleware)
    
    # Error handling
    app.add_middleware(ErrorHandlingMiddleware)
    
    # Request logging (последний, чтобы логировать всё)
    app.add_middleware(RequestLoggingMiddleware)
    
    logger.info("Middleware setup completed")
