# config.py - Централизованная конфигурация для LOKAL Cloud
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from typing import Optional, List
from pathlib import Path
import secrets


class Settings(BaseSettings):
    """Настройки приложения с валидацией"""
    
    # Основные настройки
    APP_NAME: str = "LOKAL Cloud Service"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = Field(default="production", pattern="^(development|staging|production)$")
    
    # Сервер
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4
    RELOAD: bool = False
    
    # Безопасность
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 дней
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    # CORS
    ALLOWED_ORIGINS: List[str] = ["*"]  # В продакшне заменить на конкретные домены
    ALLOW_CREDENTIALS: bool = True
    ALLOWED_METHODS: List[str] = ["*"]
    ALLOWED_HEADERS: List[str] = ["*"]
    
    # База данных
    DATABASE_PATH: str = "db/users.json"
    DB_BACKUP_DIR: str = "db/backups"
    DB_BACKUP_RETENTION_DAYS: int = 30
    DB_AUTO_BACKUP_INTERVAL_HOURS: int = 6
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_MAX_ATTEMPTS: int = 5
    RATE_LIMIT_WINDOW_SECONDS: int = 300  # 5 минут
    ACCOUNT_LOCK_DURATION_MINUTES: int = 30
    
    # WebSocket
    WS_PING_INTERVAL: int = 30
    WS_PING_TIMEOUT: int = 10
    WS_MAX_MESSAGE_SIZE: int = 1024 * 1024  # 1MB
    WS_MAX_CONNECTIONS_PER_USER: int = 3
    
    # Логирование
    LOG_LEVEL: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    LOG_FILE: str = "logs/lokal.log"
    LOG_MAX_SIZE_MB: int = 10
    LOG_BACKUP_COUNT: int = 5
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Аудит
    AUDIT_ENABLED: bool = True
    AUDIT_RETENTION_DAYS: int = 90
    
    # Email (для будущих уведомлений)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    EMAIL_ENABLED: bool = False
    
    # Яндекс OAuth
    YANDEX_CLIENT_ID: Optional[str] = None
    YANDEX_CLIENT_SECRET: Optional[str] = None
    YANDEX_REDIRECT_URI: Optional[str] = None
    
    # Мониторинг
    METRICS_ENABLED: bool = True
    HEALTH_CHECK_ENABLED: bool = True
    
    # Фоновые задачи
    BACKGROUND_TASKS_ENABLED: bool = True
    CLEANUP_INTERVAL_HOURS: int = 1
    
    # Ограничения
    MAX_DEVICES_PER_USER: int = 50
    MAX_SESSIONS_PER_USER: int = 5
    
    @validator("SECRET_KEY")
    def validate_secret_key(cls, v):
        if v == "your-secret-key-change-this-in-production":
            import warnings
            warnings.warn(
                "Using default SECRET_KEY! Set a secure key in production!",
                RuntimeWarning
            )
        return v
    
    @validator("ALLOWED_ORIGINS")
    def validate_cors_origins(cls, v, values):
        if values.get("ENVIRONMENT") == "production" and "*" in v:
            import warnings
            warnings.warn(
                "CORS allows all origins in production! Restrict to specific domains.",
                RuntimeWarning
            )
        return v
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Глобальный экземпляр настроек
settings = Settings()


# Вспомогательные функции
def get_database_path() -> Path:
    """Получить путь к БД"""
    return Path(settings.DATABASE_PATH)


def get_log_path() -> Path:
    """Получить путь к логам"""
    log_path = Path(settings.LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


def is_production() -> bool:
    """Проверка production окружения"""
    return settings.ENVIRONMENT == "production"


def is_development() -> bool:
    """Проверка development окружения"""
    return settings.ENVIRONMENT == "development"
