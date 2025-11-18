# auth.py - Улучшенная аутентификация для LOKAL Cloud
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, validator, Field
from fastapi import HTTPException, Depends, status, Request
from fastapi.security import OAuth2PasswordBearer
import os
import secrets
import re
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()

# Конфигурация
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or SECRET_KEY == "your-secret-key-change-this-in-production":
    # Генерируем случайный ключ если не задан
    SECRET_KEY = secrets.token_urlsafe(32)
    logger.warning("SECRET_KEY not set! Generated random key. Set SECRET_KEY in .env for production!")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 7))  # 7 дней по умолчанию
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 30))  # 30 дней

# Настройка хэширования паролей (улучшенная безопасность)
pwd_context = CryptContext(
    schemes=["bcrypt"],  # Убрали argon2 для скорости
    deprecated="auto"
)

# OAuth2 схема
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Rate limiting (простая реализация в памяти)
class RateLimiter:
    def __init__(self):
        self.attempts = {}  # IP -> [(timestamp, attempt_count)]
        self.max_attempts = 5
        self.window_seconds = 300  # 5 минут
    
    def check_rate_limit(self, identifier: str) -> bool:
        """Проверка rate limit"""
        now = datetime.utcnow()
        
        if identifier not in self.attempts:
            self.attempts[identifier] = []
        
        # Очищаем старые попытки
        self.attempts[identifier] = [
            (ts, count) for ts, count in self.attempts[identifier]
            if (now - ts).seconds < self.window_seconds
        ]
        
        # Считаем количество попыток
        total_attempts = sum(count for _, count in self.attempts[identifier])
        
        if total_attempts >= self.max_attempts:
            return False
        
        # Добавляем новую попытку
        self.attempts[identifier].append((now, 1))
        return True
    
    def reset(self, identifier: str):
        """Сброс счетчика для пользователя"""
        if identifier in self.attempts:
            del self.attempts[identifier]

rate_limiter = RateLimiter()

# ================== Модели данных ==================

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    refresh_token: Optional[str] = None

class TokenData(BaseModel):
    username: Optional[str] = None
    token_type: str = "access"  # "access" или "refresh"

class User(BaseModel):
    username: str
    email: Optional[str] = None
    is_active: bool = True
    is_superuser: bool = False
    created_at: Optional[datetime] = None

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    email: Optional[str] = None
    
    @validator('username')
    def validate_username(cls, v):
        """Валидация имени пользователя"""
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('Username can only contain letters, numbers, underscores and hyphens')
        return v
    
    @validator('password')
    def validate_password(cls, v):
        """Валидация пароля"""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v
    
    @validator('email')
    def validate_email(cls, v):
        """Валидация email"""
        if v and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('Invalid email format')
        return v

class UserInDB(User):
    hashed_password: str
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None

class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)
    
    @validator('new_password')
    def validate_new_password(cls, v):
        """Валидация нового пароля"""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one digit')
        return v

# ================== Функции для работы с паролями ==================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

def hash_password(password: str) -> str:
    """Хэширование пароля"""
    return pwd_context.hash(password)

def check_password_strength(password: str) -> dict:
    """Проверка силы пароля"""
    strength = {
        "score": 0,
        "feedback": []
    }
    
    if len(password) >= 12:
        strength["score"] += 2
    elif len(password) >= 8:
        strength["score"] += 1
    else:
        strength["feedback"].append("Password too short")
    
    if re.search(r'[A-Z]', password):
        strength["score"] += 1
    else:
        strength["feedback"].append("Add uppercase letters")
    
    if re.search(r'[a-z]', password):
        strength["score"] += 1
    else:
        strength["feedback"].append("Add lowercase letters")
    
    if re.search(r'\d', password):
        strength["score"] += 1
    else:
        strength["feedback"].append("Add numbers")
    
    if re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        strength["score"] += 2
    else:
        strength["feedback"].append("Add special characters")
    
    # Итоговая оценка
    if strength["score"] >= 6:
        strength["level"] = "strong"
    elif strength["score"] >= 4:
        strength["level"] = "medium"
    else:
        strength["level"] = "weak"
    
    return strength

# ================== Функции для работы с JWT ==================

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    token_type: str = "access"
) -> str:
    """Создание JWT токена"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        if token_type == "refresh":
            expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": token_type
    })
    
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"Token creation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create authentication token"
        )

def decode_token(token: str) -> dict:
    """Декодирование JWT токена"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Проверяем срок действия
        exp = payload.get("exp")
        if exp and datetime.utcfromtimestamp(exp) < datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return payload
    except JWTError as e:
        logger.warning(f"Token decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def create_tokens(username: str) -> dict:
    """Создание пары access и refresh токенов"""
    access_token = create_access_token(
        data={"sub": username},
        token_type="access"
    )
    
    refresh_token = create_access_token(
        data={"sub": username},
        token_type="refresh"
    )
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }

# ================== Зависимости для FastAPI ==================

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db_manager = None  # Будет передаваться через Depends
) -> User:
    """Получение текущего пользователя по токену"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = decode_token(token)
        username: str = payload.get("sub")
        token_type: str = payload.get("type", "access")
        
        if username is None:
            raise credentials_exception
        
        # Проверяем тип токена
        if token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Получаем пользователя из БД
        if db_manager:
            user_data = db_manager.get_user(username)
            if not user_data:
                raise credentials_exception
            
            # Проверяем блокировку
            if user_data.get("locked_until"):
                locked_until = datetime.fromisoformat(user_data["locked_until"])
                if locked_until > datetime.utcnow():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Account locked until {locked_until.isoformat()}"
                    )
            
            # Проверяем активность
            if not user_data.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account is inactive"
                )
        
        return User(username=username)
        
    except JWTError:
        raise credentials_exception

async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Проверка активности пользователя"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user

async def get_current_superuser(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Проверка прав суперпользователя"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user

def check_rate_limit_dependency(request: Request):
    """Зависимость для проверки rate limit"""
    client_ip = request.client.host
    
    if not rate_limiter.check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later."
        )
    
    return True

# ================== Утилиты безопасности ==================

def sanitize_input(input_str: str, max_length: int = 1000) -> str:
    """Очистка входных данных"""
    if not input_str:
        return ""
    
    # Обрезаем до максимальной длины
    sanitized = input_str[:max_length]
    
    # Удаляем потенциально опасные символы
    # (можно расширить при необходимости)
    dangerous_patterns = [
        r'<script', r'javascript:', r'onerror=', r'onload='
    ]
    
    for pattern in dangerous_patterns:
        sanitized = re.sub(pattern, '', sanitized, flags=re.IGNORECASE)
    
    return sanitized.strip()

def generate_secure_token(length: int = 32) -> str:
    """Генерация безопасного случайного токена"""
    return secrets.token_urlsafe(length)

