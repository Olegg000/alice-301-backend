# db_manager.py - Управление базой данных для LOKAL Cloud
from tinydb import TinyDB, Query
from typing import Optional, List, Dict, Any
import json
import os
from threading import Lock
from datetime import datetime, timedelta


class DatabaseManager:
    """Менеджер для работы с TinyDB"""
    
    def __init__(self, db_path: str = "db/users.json"):
        """Инициализация базы данных"""
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self.db = TinyDB(db_path)
        self.users = self.db.table('users')
        self.auth_codes = self.db.table('auth_codes')
        self.sessions = self.db.table('sessions')
        
        self.lock = Lock()
        
        self.User = Query()
        self.Code = Query()
        self.Session = Query()

    # ================== Работа с сессиями ==================

    def create_session(self, username: str, token: str, ip_address: str, user_agent: str):
        """Создание новой сессии пользователя"""
        with self.lock:
            self.sessions.insert({
                'username': username,
                'token': token,
                'ip_address': ip_address,
                'user_agent': user_agent,
                'created_at': datetime.now().isoformat(),
                'last_activity': datetime.now().isoformat()
            })

    def get_user_sessions(self, username: str) -> List[Dict[str, Any]]:
        """Получение всех активных сессий пользователя"""
        with self.lock:
            return self.sessions.search(self.Session.username == username)

    def revoke_session(self, token: str):
        """Отзыв конкретной сессии по токену"""
        with self.lock:
            self.sessions.remove(self.Session.token == token)

    def revoke_all_sessions(self, username: str):
        """Отзыв всех сессий для указанного пользователя"""
        with self.lock:
            self.sessions.remove(self.Session.username == username)

    # ================== Управление блокировкой ==================

    def is_user_locked(self, username: str) -> bool:
        """Проверка, заблокирован ли пользователь"""
        user = self.get_user(username)
        if not user or not user.get('lockout_until'):
            return False

        lockout_until = datetime.fromisoformat(user['lockout_until'])
        if datetime.now() < lockout_until:
            return True

        self.reset_failed_attempts(username)
        return False

    def increment_failed_attempts(self, username: str):
        """Увеличение счетчика неудачных попыток входа"""
        with self.lock:
            user = self.get_user(username)
            if not user:
                return

            attempts = user.get('failed_login_attempts', 0) + 1

            update_data = {
                'failed_login_attempts': attempts,
                'updated_at': datetime.now().isoformat()
            }

            LOCKOUT_ATTEMPTS = 5
            LOCKOUT_MINUTES = 15
            if attempts >= LOCKOUT_ATTEMPTS:
                lockout_until = datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)
                update_data['lockout_until'] = lockout_until.isoformat()

            self.users.update(update_data, self.User.username == username)

    def reset_failed_attempts(self, username: str):
        """Сброс счетчика неудачных попыток входа"""
        with self.lock:
            self.users.update(
                {
                    'failed_login_attempts': 0,
                    'lockout_until': None,
                    'updated_at': datetime.now().isoformat()
                },
                self.User.username == username
            )
    
    # ================== Работа с пользователями ==================
    
    def create_user(self, username: str, hashed_password: str) -> bool:
        """Создание нового пользователя"""
        with self.lock:
            if self.users.search(self.User.username == username):
                return False

            self.users.insert({
                'username': username,
                'hashed_password': hashed_password,
                'yandex_token': None,
                'yandex_refresh_token': None,
                'devices': [],
                'is_active': True,
                'is_superuser': False,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'failed_login_attempts': 0,
                'lockout_until': None
            })
            return True
    
    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Получение пользователя по имени"""
        with self.lock:
            result = self.users.search(self.User.username == username)
            return result[0] if result else None
    
    def update_user(self, username: str, updates: Dict[str, Any]) -> bool:
        """Обновление данных пользователя"""
        with self.lock:
            updates['updated_at'] = datetime.now().isoformat()
            return self.users.update(updates, self.User.username == username)

    def update_user_devices(self, username: str, devices: List[Dict[str, Any]]) -> bool:
        """Обновление с timestamp"""
        with self.lock:
            return self.users.update(
                {
                    'devices': devices,
                    'devices_updated_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                },
                self.User.username == username
            )
    
    def get_user_devices(self, username: str) -> List[Dict[str, Any]]:
        """Получение списка устройств пользователя"""
        user = self.get_user(username)
        return user.get('devices', []) if user else []
    
    # ================== Работа с токенами Яндекса ==================
    
    def save_yandex_token(self, username: str, token: str, refresh_token: str = None) -> bool:
        """Сохранение токена Яндекса для пользователя"""
        with self.lock:
            return self.users.update(
                {
                    'yandex_token': token,
                    'yandex_refresh_token': refresh_token,
                    'updated_at': datetime.now().isoformat()
                },
                self.User.username == username
            )
    
    def get_username_by_yandex_token(self, token: str) -> Optional[str]:
        """Получение имени пользователя по токену Яндекса"""
        with self.lock:
            result = self.users.search(self.User.yandex_token == token)
            return result[0]['username'] if result else None
    
    def clear_yandex_token(self, username: str) -> bool:
        """Удаление токена Яндекса"""
        with self.lock:
            return self.users.update(
                {
                    'yandex_token': None,
                    'yandex_refresh_token': None,
                    'updated_at': datetime.now().isoformat()
                },
                self.User.username == username
            )
    
    # ================== Работа с кодами авторизации ==================
    
    def save_auth_code(self, code: str, username: str, client_id: str = None) -> bool:
        """Сохранение временного кода авторизации"""
        with self.lock:
            # Удаляем старые коды этого пользователя
            self.auth_codes.remove(self.Code.username == username)
            
            # Сохраняем новый код
            self.auth_codes.insert({
                'code': code,
                'username': username,
                'client_id': client_id,
                'created_at': datetime.now().isoformat(),
                'expires_at': (datetime.now() + timedelta(minutes=10)).isoformat(),
                'used': False
            })
            return True
    
    def get_username_by_code(self, code: str, mark_as_used: bool = False) -> Optional[str]:
        """Получение имени пользователя по коду авторизации"""
        with self.lock:
            result = self.auth_codes.search(self.Code.code == code)
            if not result:
                return None
            
            auth_code = result[0]
            
            # Проверка использования
            if auth_code.get('used', False):
                return None
            
            # Проверка срока действия
            expires_at = datetime.fromisoformat(auth_code['expires_at'])
            if datetime.now() > expires_at:
                self.auth_codes.remove(self.Code.code == code)
                return None
            
            # Помечаем как использованный
            if mark_as_used:
                self.auth_codes.update({'used': True}, self.Code.code == code)
            
            return auth_code['username']
    
    def delete_auth_code(self, code: str) -> bool:
        """Удаление использованного кода авторизации"""
        with self.lock:
            return self.auth_codes.remove(self.Code.code == code)
    
    # ================== Утилиты ==================
    
    def cleanup_expired_codes(self):
        """Очистка истекших кодов авторизации"""
        with self.lock:
            now = datetime.now()
            expired_codes = []
            
            for code in self.auth_codes.all():
                if datetime.fromisoformat(code['expires_at']) < now:
                    expired_codes.append(code.doc_id)
            
            for doc_id in expired_codes:
                self.auth_codes.remove(doc_ids=[doc_id])
            
            return len(expired_codes)
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики базы данных"""
        with self.lock:
            return {
                'total_users': len(self.users),
                'active_auth_codes': len(self.auth_codes),
                'users_with_yandex': len(self.users.search(self.User.yandex_token != None)),
                'total_devices': sum(len(user.get('devices', [])) for user in self.users.all())
            }
    
    def get_audit_log(self, username: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Получение audit log (заглушка для расширения)"""
        # В реальной системе здесь была бы отдельная таблица для аудита
        return []
    
    def create_backup(self) -> str:
        """Создание резервной копии БД"""
        import shutil
        from pathlib import Path
        
        backup_dir = Path("db/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"backup_{timestamp}.json"
        
        # Закрываем и копируем БД
        db_file = Path(self.db._storage._handle.name)
        shutil.copy2(db_file, backup_file)
        
        return str(backup_file)
    
    def close(self):
        """Закрытие базы данных"""
        self.db.close()
