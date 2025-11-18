# websocket_manager.py - управление WebSocket-соединениями с домашними агентами
from typing import Dict, Optional, List, Any, Callable
from fastapi import WebSocket, WebSocketDisconnect
import json
import asyncio
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
import time

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """Состояние WebSocket соединения"""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class ConnectionInfo:
    """Информация о WebSocket соединении"""
    username: str
    websocket: WebSocket
    state: ConnectionState = ConnectionState.CONNECTING
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_ping: Optional[datetime] = None
    last_pong: Optional[datetime] = None
    messages_sent: int = 0
    messages_received: int = 0
    errors: int = 0
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class WebSocketManager:
    """Улучшенный менеджер WebSocket соединений с домашними агентами"""

    def __init__(
            self,
            ping_interval: int = 30,
            ping_timeout: int = 10,
    ):
        self.connections: Dict[str, ConnectionInfo] = {}
        self.pending_responses: Dict[str, asyncio.Future] = {}
        self.on_connect_callbacks: List[Callable] = []
        self.on_disconnect_callbacks: List[Callable] = []
        self.on_message_callbacks: List[Callable] = []

        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout

        self.stats = {
            'total_connections': 0,
            'total_disconnections': 0,
            'messages_sent': 0,
            'messages_received': 0,
            'errors': 0,
            'ping_timeouts': 0
        }

        self._monitor_task = None
        self._running = False

    async def handle_full_connection(
            self,
            username: str,
            websocket: WebSocket,
            ip_address: Optional[str] = None,
            user_agent: Optional[str] = None
    ):
        """
        Главный метод, который принимает WebSocket и управляет всем его жизненным циклом.
        Именно его должен вызывать эндпоинт в main.py.
        """
        await self.connect(username, websocket, ip_address, user_agent)
        reason = "Normal closure"
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                await self.handle_message(username, message)
        except WebSocketDisconnect as e:
            reason = f"Client disconnected (code: {e.code}, reason: {e.reason or 'N/A'})"
            logger.info(f"WebSocket gracefully disconnected for {username}. Reason: {reason}")
        except json.JSONDecodeError:
            reason = "Invalid JSON received"
            logger.warning(f"Invalid JSON from {username}. Disconnecting.")
        except Exception as e:
            reason = f"Unexpected error: {e}"
            logger.error(f"Error in WebSocket loop for {username}: {e}", exc_info=True)
        finally:
            # Гарантированное отключение и очистка ресурсов
            await self.disconnect(username, reason=reason)

    async def start(self):
        """Запуск менеджера"""
        if self._running: return
        self._running = True
        self._monitor_task = asyncio.create_task(self._connection_monitor())
        logger.info("WebSocket manager started")

    async def stop(self):
        """Остановка менеджера"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        for username in list(self.connections.keys()):
            await self.disconnect(username, reason="Server shutting down")

        logger.info("WebSocket manager stopped")

    async def _connection_monitor(self):
        """Мониторинг соединений (ping/pong, таймауты)"""
        while self._running:
            try:
                now = datetime.utcnow()
                disconnected_users = []

                # Копируем ключи, чтобы избежать изменения словаря во время итерации
                for username, conn_info in list(self.connections.items()):
                    # Проверяем таймаут pong
                    if conn_info.last_ping and not conn_info.last_pong:
                        if (now - conn_info.last_ping).total_seconds() > self.ping_timeout:
                            logger.warning(f"Ping timeout for {username}, disconnecting.")
                            self.stats['ping_timeouts'] += 1
                            disconnected_users.append((username, "Ping timeout"))
                            continue

                    # Отправляем ping, если прошло достаточно времени
                    time_since_last_ping = (
                                now - conn_info.last_ping).total_seconds() if conn_info.last_ping else self.ping_interval
                    if time_since_last_ping >= self.ping_interval:
                        try:
                            await self._send_ping(username)
                        except Exception:
                            # Если отправка пинга не удалась, значит соединение уже разорвано
                            disconnected_users.append((username, "Failed to send ping"))

                # Отключаем проблемные соединения
                for username, reason in disconnected_users:
                    await self.disconnect(username, reason=reason)

                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Critical error in connection monitor: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _send_ping(self, username: str):
        """Отправка ping сообщения"""
        conn_info = self.connections.get(username)
        if not conn_info: return

        conn_info.last_ping = datetime.utcnow()
        conn_info.last_pong = None
        await self.send_personal_message(username, {"type": "ping"})

    async def _handle_pong(self, username: str):
        """Обработка pong от клиента"""
        conn_info = self.connections.get(username)
        if conn_info:
            conn_info.last_pong = datetime.utcnow()

    async def connect(
            self,
            username: str,
            websocket: WebSocket,
            ip_address: Optional[str] = None,
            user_agent: Optional[str] = None
    ):
        """Подключение нового агента"""
        await websocket.accept()
        if username in self.connections:
            logger.warning(f"New connection for {username} while old one exists. Closing old one.")
            await self.disconnect(username, reason="New connection established")

        conn_info = ConnectionInfo(
            username=username, websocket=websocket, state=ConnectionState.CONNECTED,
            ip_address=ip_address, user_agent=user_agent
        )
        self.connections[username] = conn_info
        self.stats['total_connections'] += 1

        for callback in self.on_connect_callbacks:
            asyncio.create_task(callback(username, conn_info))

    async def disconnect(self, username: str, reason: str = "Normal closure"):
        """Отключение агента"""
        if username not in self.connections: return

        conn_info = self.connections.pop(username)
        conn_info.state = ConnectionState.DISCONNECTING

        try:
            await conn_info.websocket.close(code=1000, reason=reason)
        except Exception:
            pass

        self.stats['total_disconnections'] += 1

        for request_id in [k for k in self.pending_responses if k.startswith(f"{username}_")]:
            future = self.pending_responses.pop(request_id, None)
            if future and not future.done():
                future.set_exception(ConnectionAbortedError(f"Agent disconnected: {reason}"))

        for callback in self.on_disconnect_callbacks:
            asyncio.create_task(callback(username, reason))

    async def handle_message(self, username: str, message: Dict[str, Any]):
        """Обработка входящего сообщения от агента"""
        if username not in self.connections: return

        conn_info = self.connections[username]
        conn_info.messages_received += 1
        self.stats['messages_received'] += 1

        message_type = message.get("type")

        if message_type == "pong":
            await self._handle_pong(username)
            return

        request_id = message.get("request_id")
        if request_id and request_id in self.pending_responses:
            future = self.pending_responses.get(request_id)
            if future and not future.done():
                if message_type == "status_response":
                    future.set_result(message.get("devices", []))
                else:
                    future.set_result(message)

        for callback in self.on_message_callbacks:
            asyncio.create_task(callback(username, message))

    async def send_personal_message(
            self,
            username: str,
            message: Dict[str, Any],
            timeout: Optional[int] = 5
    ) -> bool:
        """Отправка сообщения конкретному агенту"""
        if username not in self.connections:
            logger.warning(f"No active connection for user: {username}")
            return False

        conn_info = self.connections[username]

        try:
            message_json = json.dumps(message)

            if timeout:
                await asyncio.wait_for(
                    conn_info.websocket.send_text(message_json),
                    timeout=timeout
                )
            else:
                await conn_info.websocket.send_text(message_json)

            conn_info.messages_sent += 1
            self.stats['messages_sent'] += 1

            return True

        except asyncio.TimeoutError:
            logger.error(f"Timeout sending message to {username}")
            self.stats['errors'] += 1
            conn_info.errors += 1
            await self.disconnect(username, "Send timeout")
            return False

        except Exception as e:
            logger.error(f"Error sending message to {username}: {e}")
            self.stats['errors'] += 1
            conn_info.errors += 1
            await self.disconnect(username, f"Send error: {e}")
            return False

    async def request_device_status(
            self,
            username: str,
            device_ids: List[str],
            timeout: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """Запрос статуса устройств у агента"""
        if username not in self.connections:
            logger.warning(f"Cannot request status: {username} not connected")
            return None

        # Генерируем уникальный ID запроса
        request_id = f"{username}_{int(time.time() * 1000)}"

        # Создаем Future для ожидания ответа
        future = asyncio.Future()
        self.pending_responses[request_id] = future

        # Отправляем запрос агенту
        message = {
            "type": "query_status",
            "request_id": request_id,
            "devices": device_ids
        }

        success = await self.send_personal_message(username, message)
        if not success:
            del self.pending_responses[request_id]
            return None

        try:
            # Ждем ответ с таймаутом
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for status from {username}")
            return None

        except Exception as e:
            logger.error(f"Error waiting for status from {username}: {e}")
            return None

        finally:
            # Удаляем из ожидающих
            if request_id in self.pending_responses:
                del self.pending_responses[request_id]

    async def send_command(
            self,
            username: str,
            commands: List[Dict[str, Any]],
            wait_for_response: bool = False,
            timeout: int = 10
    ) -> bool:
        """Отправка команды управления агенту"""
        if username not in self.connections:
            logger.warning(f"Cannot send command: {username} not connected")
            return False

        request_id = f"{username}_cmd_{int(time.time() * 1000)}" if wait_for_response else None

        message = {
            "type": "execute_command",
            "commands": commands,
            "timestamp": datetime.utcnow().isoformat()
        }

        if request_id:
            message["request_id"] = request_id
            future = asyncio.Future()
            self.pending_responses[request_id] = future

        success = await self.send_personal_message(username, message)

        if not success:
            if request_id and request_id in self.pending_responses:
                del self.pending_responses[request_id]
            return False

        if wait_for_response and request_id:
            try:
                await asyncio.wait_for(future, timeout=timeout)
                return True
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for command response from {username}")
                return False
            finally:
                if request_id in self.pending_responses:
                    del self.pending_responses[request_id]

        return True

    async def handle_message(self, username: str, message: Dict[str, Any]):
        """Обработка входящего сообщения от агента"""
        if username not in self.connections:
            return

        conn_info = self.connections[username]
        conn_info.messages_received += 1
        self.stats['messages_received'] += 1

        message_type = message.get("type")

        # Обработка pong
        if message_type == "pong":
            await self._handle_pong(username)
            return

        # Обработка ответов на запросы
        request_id = message.get("request_id")
        if request_id and request_id in self.pending_responses:
            future = self.pending_responses[request_id]
            if not future.done():
                if message_type == "status_response":
                    future.set_result(message.get("devices", []))
                elif message_type == "command_response":
                    future.set_result(message.get("success", False))
                else:
                    future.set_result(message)

        # Вызываем callbacks
        for callback in self.on_message_callbacks:
            try:
                await callback(username, message)
            except Exception as e:
                logger.error(f"Error in message callback: {e}")

    async def broadcast_message(
            self,
            message: Dict[str, Any],
            exclude: Optional[List[str]] = None
    ) -> int:
        """Отправка сообщения всем подключенным агентам"""
        exclude = exclude or []
        success_count = 0

        for username in list(self.connections.keys()):
            if username not in exclude:
                if await self.send_personal_message(username, message):
                    success_count += 1

        return success_count

    # ================== Callback управление ==================

    def on_connect(self, callback: Callable):
        """Регистрация callback для события подключения"""
        self.on_connect_callbacks.append(callback)

    def on_disconnect(self, callback: Callable):
        """Регистрация callback для события отключения"""
        self.on_disconnect_callbacks.append(callback)

    def on_message(self, callback: Callable):
        """Регистрация callback для входящих сообщений"""
        self.on_message_callbacks.append(callback)

    # ================== Статистика и мониторинг ==================

    def is_connected(self, username: str) -> bool:
        """Проверка активности соединения"""
        return username in self.connections

    def get_connection_info(self, username: str) -> Optional[ConnectionInfo]:
        """Получение информации о соединении"""
        return self.connections.get(username)

    def get_active_users(self) -> List[str]:
        """Получение списка подключенных пользователей"""
        return list(self.connections.keys())

    def get_connection_count(self) -> int:
        """Количество активных соединений"""
        return len(self.connections)

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики"""
        return {
            **self.stats,
            'active_connections': len(self.connections),
            'pending_responses': len(self.pending_responses),
            'uptime_seconds': sum(
                (datetime.utcnow() - conn.connected_at).seconds
                for conn in self.connections.values()
            ) / max(len(self.connections), 1)
        }

    def get_detailed_stats(self) -> Dict[str, Any]:
        """Получение детальной статистики по каждому соединению"""
        connections_stats = []

        for username, conn in self.connections.items():
            uptime = (datetime.utcnow() - conn.connected_at).seconds

            latency = None
            if conn.last_ping and conn.last_pong:
                latency = (conn.last_pong - conn.last_ping).total_seconds() * 1000

            connections_stats.append({
                'username': username,
                'state': conn.state.value,
                'uptime_seconds': uptime,
                'messages_sent': conn.messages_sent,
                'messages_received': conn.messages_received,
                'errors': conn.errors,
                'latency_ms': latency,
                'ip_address': conn.ip_address,
                'last_ping': conn.last_ping.isoformat() if conn.last_ping else None,
                'last_pong': conn.last_pong.isoformat() if conn.last_pong else None
            })

        return {
            'global_stats': self.get_stats(),
            'connections': connections_stats
        }
