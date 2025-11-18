from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, Request, Query, Form
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Annotated
from datetime import datetime
import logging
import json
import uuid

from config import settings, is_production
from auth import (
    create_tokens, verify_password, decode_token, get_current_user,
    get_current_superuser, check_rate_limit_dependency, rate_limiter,
    sanitize_input, User, UserCreate, PasswordChange, Token, hash_password
)
from db_manager import DatabaseManager
from websocket_manager import WebSocketManager
from yandex_api import YandexSmartHome
from middleware import setup_middleware, metrics_middleware
from scheduler import BackgroundTasksManager

# Настройка логирования
from logging.handlers import RotatingFileHandler
import os

os.makedirs(os.path.dirname(settings.LOG_FILE), exist_ok=True)

log_formatter = logging.Formatter(settings.LOG_FORMAT)
file_handler = RotatingFileHandler(
    settings.LOG_FILE,
    maxBytes=settings.LOG_MAX_SIZE_MB * 1024 * 1024,
    backupCount=settings.LOG_BACKUP_COUNT
)
file_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    handlers=[file_handler, console_handler]
)

logger = logging.getLogger(__name__)

# Инициализация компонентов
db = DatabaseManager(db_path=settings.DATABASE_PATH)
ws_manager = WebSocketManager() # Передаем DB для возможности логирования
yandex = YandexSmartHome(db, ws_manager)
background_tasks = BackgroundTasksManager(db, ws_manager)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения: запуск и остановка служб."""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")

    # Запускаем фоновые задачи и WebSocket менеджер
    await ws_manager.start()
    await background_tasks.start()

    stats = db.get_stats()
    logger.info(f"Database loaded: {stats['total_users']} users, {stats['total_devices']} devices")

    yield  # <-- Приложение работает здесь

    logger.info("Shutting down services...")
    background_tasks.stop()
    await ws_manager.stop()
    db.close()
    logger.info("Shutdown complete")


# ================== FastAPI App Initialization ==================

app = FastAPI(
    title=settings.APP_NAME,
    description="Production-ready облачный сервис для интеграции с Яндекс Алисой",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if not is_production() else None,
    redoc_url="/redoc" if not is_production() else None
)

# Подключаем middleware (CORS, Rate Limiting и т.д.)
setup_middleware(app)

# ================== Health & Status Endpoints ==================

@app.get("/")
async def root():
    """Главная страница"""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check для мониторинга"""
    try:
        db_stats = db.get_stats()
        ws_stats = ws_manager.get_stats()

        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "database": "ok",
                "websocket": "ok",
                "scheduler": "ok" if background_tasks.is_running() else "warning"
            },
            "metrics": {
                "users": db_stats.get("total_users"),
                "active_connections": ws_stats.get("active_connections")
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


# ================== Authentication Endpoints ==================

@app.post("/register", response_model=Token)
async def register(
    request: Request,
    user: UserCreate,
    _: bool = Depends(check_rate_limit_dependency)
):
    """Регистрация нового пользователя"""
    username = sanitize_input(user.username)

    if db.get_user(username):
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_pwd = hash_password(user.password)
    success = db.create_user(username=username, hashed_password=hashed_pwd)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to create user")

    rate_limiter.reset(request.client.host)
    tokens = create_tokens(username)

    logger.info(f"New user registered: {username}")
    return tokens

@app.post("/token", response_model=Token)
async def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    _: bool = Depends(check_rate_limit_dependency)
):
    """Получение JWT токена"""
    username = sanitize_input(form_data.username)

    logger.info(f"Login attempt for '{username}'")

    if db.is_user_locked(username):
        logger.warning(f"Login blocked: {username} is locked")
        raise HTTPException(status_code=403, detail="Account locked")

    user = db.get_user(username)

    if not user or not verify_password(form_data.password, user["hashed_password"]):
        db.increment_failed_attempts(username)
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account is inactive")

    db.reset_failed_attempts(username)
    rate_limiter.reset(request.client.host)

    tokens = create_tokens(username)
    db.create_session(
        username,
        tokens["access_token"],
        request.client.host,
        request.headers.get("user-agent", "")
    )
    logger.info(f"User logged in: {username}")
    return tokens


@app.post("/refresh")
async def refresh_token(refresh_token: str):
    """Обновление access токена"""
    try:
        payload = decode_token(refresh_token)

        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")

        from auth import create_access_token
        new_access_token = create_access_token(data={"sub": username}, token_type="access")

        return {"access_token": new_access_token, "token_type": "bearer"}

    except Exception as e:
        logger.warning(f"Token refresh failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@app.post("/change-password")
async def change_password(
    password_change: PasswordChange,
    current_user: Annotated[User, Depends(get_current_user)]
):
    """Смена пароля"""
    user = db.get_user(current_user.username)

    if not user or not verify_password(password_change.old_password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect old password")

    new_hashed_pwd = hash_password(password_change.new_password)
    db.update_user(current_user.username, {"hashed_password": new_hashed_pwd})
    db.revoke_all_sessions(current_user.username)

    logger.info(f"Password changed for user: {current_user.username}")
    return {"message": "Password changed successfully. Please log in again."}

@app.post("/logout")
async def logout(request: Request, current_user: Annotated[User, Depends(get_current_user)]):
    """Выход из системы"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        db.revoke_session(token)

    logger.info(f"User logged out: {current_user.username}")
    return {"message": "Logged out successfully"}


# ================== User Management Endpoints ==================

@app.get("/me")
async def get_current_user_info(current_user: Annotated[User, Depends(get_current_user)]):
    """Информация о текущем пользователе"""
    user_data = db.get_user(current_user.username)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    # Безопасно возвращаем данные (без хешированного пароля)
    return {
        "username": user_data["username"],
        "is_active": user_data.get("is_active", True),
        "created_at": user_data.get("created_at"),
        "last_login": user_data.get("last_login"),
        "devices_count": len(db.get_user_devices(current_user.username)),
        "yandex_connected": bool(user_data.get("yandex_token"))
    }



@app.get("/me/sessions")
async def get_user_sessions(current_user: User = Depends(get_current_user)):
    """Получение списка активных сессий"""
    sessions = db.get_user_sessions(current_user.username)

    return {
        "sessions": [
            {
                "ip_address": s.get("ip_address"),
                "user_agent": s.get("user_agent"),
                "created_at": s.get("created_at"),
                "last_activity": s.get("last_activity")
            }
            for s in sessions
        ]
    }


# ================== Яндекс OAuth Endpoints ==================

@app.get("/auth")
async def oauth_authorize(
        request: Request,
        client_id: str = Query(...),
        redirect_uri: str = Query(...),
        response_type: str = Query(...),
        state: str = Query(...)
):
    """OAuth авторизация для Яндекса"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>LOKAL - Авторизация</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                   background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                   min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
            .container {{ background: white; padding: 40px; border-radius: 16px; 
                         box-shadow: 0 20px 60px rgba(0,0,0,0.3); max-width: 400px; width: 90%; }}
            h2 {{ color: #333; margin-bottom: 10px; font-size: 28px; }}
            p {{ color: #666; margin-bottom: 30px; }}
            input {{ width: 100%; padding: 14px; margin: 10px 0; border: 2px solid #e0e0e0; 
                    border-radius: 8px; font-size: 14px; transition: all 0.3s; }}
            input:focus {{ border-color: #667eea; outline: none; }}
            button {{ width: 100%; padding: 14px; background: #667eea; color: white; border: none; 
                     border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; 
                     transition: all 0.3s; margin-top: 10px; }}
            button:hover {{ background: #5568d3; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4); }}
            .logo {{ text-align: center; margin-bottom: 20px; }}
            .logo svg {{ width: 60px; height: 60px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <svg viewBox="0 0 24 24" fill="none"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" stroke="#667eea" stroke-width="2"/></svg>
            </div>
            <h2>🏠 LOKAL</h2>
            <p>Войдите для подключения к Яндекс Умному Дому</p>
            <form method="post" action="/auth/callback">
                <input type="hidden" name="client_id" value="{client_id}">
                <input type="hidden" name="redirect_uri" value="{redirect_uri}">
                <input type="hidden" name="state" value="{state}">
                <input type="text" name="username" placeholder="Имя пользователя" required autofocus>
                <input type="password" name="password" placeholder="Пароль" required>
                <button type="submit">Войти</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post("/auth/callback")
async def oauth_callback(
        client_id: Annotated[str, Form()],
        redirect_uri: Annotated[str, Form()],
        state: Annotated[str, Form()],
        username: Annotated[str, Form()],
        password: Annotated[str, Form()]
):
    """Обработка OAuth callback"""
    clean_username = sanitize_input(username)

    user = db.get_user(clean_username)
    if not user or not verify_password(password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    auth_code = str(uuid.uuid4())
    db.save_auth_code(auth_code, clean_username, client_id=client_id)

    return RedirectResponse(url=f"{redirect_uri}?code={auth_code}&state={state}")


@app.post("/auth/token")
async def oauth_token(request: Request):
    """Обмен authorization code на access token"""
    form = await request.form()
    code = form.get("code")

    username = db.get_username_by_code(code, mark_as_used=True)
    if not username:
        raise HTTPException(status_code=400, detail="Invalid authorization code")

    # Генерируем токен для Яндекса
    import uuid
    yandex_token = str(uuid.uuid4())
    db.save_yandex_token(username, yandex_token)

    return {
        "access_token": yandex_token,
        "token_type": "bearer",
        "expires_in": 31536000  # 1 год
    }


# ================== Яндекс Smart Home API ==================

@app.head("/v1.0/")
async def yandex_health():
    return ""


@app.post("/v1.0/user/unlink")
async def yandex_unlink(request: Request):
    return await yandex.unlink_account(request)


@app.get("/v1.0/user/devices")
async def yandex_devices(request: Request):
    return await yandex.get_devices(request)


@app.post("/v1.0/user/devices/query")
async def yandex_query(request: Request):
    return await yandex.query_devices(request)


@app.post("/v1.0/user/devices/action")
async def yandex_action(request: Request):
    return await yandex.execute_action(request)


@app.post("/api/v1/user/devices", status_code=200, tags=["User"])
async def update_user_devices(
    devices: List[Dict[str, Any]],
    current_user: Annotated[User, Depends(get_current_user)]
):
    """Обновление списка устройств от LOKAL агента"""
    username = current_user.username
    if len(devices) > settings.MAX_DEVICES_PER_USER:
        raise HTTPException(
            status_code=413,
            detail=f"Превышен лимит устройств. Максимум: {settings.MAX_DEVICES_PER_USER}."
        )
    db.update_user_devices(username, devices)
    logger.info(f"Обновлен список устройств для {username}: {len(devices)} шт.")
    return {"message": "Список устройств успешно обновлен."}


# ================== WebSocket Endpoint ==================

@app.websocket("/ws/agent/{token}")
async def websocket_agent(websocket: WebSocket, token: str):
    """
    WebSocket эндпоинт для агента.
    Аутентифицирует агента и передает полное управление соединением
    в WebSocketManager для обработки всего жизненного цикла.
    """
    username = None
    try:
        payload = decode_token(token)
        username = payload.get("sub")
        if not username or not db.get_user(username):
            await websocket.close(code=1008, reason="Invalid or unknown user")
            return
    except Exception:
        await websocket.close(code=1008, reason="Invalid token")
        return

    # Одна строка, которая делает все. Эндпоинт больше ни за что не отвечает.
    await ws_manager.handle_full_connection(
        username=username,
        websocket=websocket,
        ip_address=websocket.client.host,
        user_agent=websocket.headers.get("user-agent", "")
    )


# ================== Admin Endpoints ==================

@app.get("/admin/stats")
async def admin_stats(current_user: User = Depends(get_current_superuser)):
    """Получение полной статистики (только для админов)"""
    return {
        "database": db.get_stats(),
        "websocket": ws_manager.get_detailed_stats(),
        "tasks": background_tasks.get_tasks_status(),
        "metrics": metrics_middleware.get_metrics() if metrics_middleware else {}
    }


@app.get("/admin/audit")
async def admin_audit(
        username: Optional[str] = None,
        limit: int = 100,
        current_user: User = Depends(get_current_superuser)
):
    """Получение audit log"""
    return db.get_audit_log(username=username, limit=limit)


@app.post("/admin/tasks/{task_id}/run")
async def run_task(
        task_id: str,
        current_user: User = Depends(get_current_superuser)
):
    """Запуск фоновой задачи вручную"""
    success = await background_tasks.run_task_now(task_id)
    if success:
        return {"message": f"Task {task_id} scheduled for execution"}
    raise HTTPException(status_code=404, detail="Task not found")


@app.post("/admin/backup")
async def create_backup(current_user: User = Depends(get_current_superuser)):
    """Создание резервной копии БД"""
    try:
        backup_file = db.create_backup()
        return {"message": "Backup created", "file": backup_file}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================== Запуск ==================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=True
    )
