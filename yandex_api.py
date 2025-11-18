# yandex_api.py - обработчик Smart Home API Яндекса

from typing import Dict, List, Any, Optional
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime
import asyncio
import uuid
import logging

logger = logging.getLogger(__name__)


class YandexSmartHome:
    """Обработчик запросов от Яндекс Умного Дома"""

    def __init__(self, db_manager, ws_manager):
        self.db = db_manager
        self.ws_manager = ws_manager

    def _get_username_from_request(self, request: Request) -> str:
        """Извлечение пользователя из токена в заголовке"""
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization header")

        token = auth_header[7:]
        username = self.db.get_username_by_yandex_token(token)

        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")

        return username

    def _convert_device_to_yandex_format(self, device: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Конвертация устройства в формат Яндекса"""
        device_id = device.get("id")
        if not device_id:
            return None
            
        yandex_device = {
            "id": device_id,
            "name": device.get("name", f"Устройство {device_id[-4:]}"),
            "type": "devices.types.light",
            "capabilities": [
                {
                    "type": "devices.capabilities.on_off",
                    "retrievable": True,
                    "reportable": True, # Говорим Яндексу, что можем сообщать об изменениях
                }
            ],
            "device_info": {
                "manufacturer": "LOKAL",
                "model": device.get("product_name", "Smart Device"),
                "sw_version": "1.0"
            }
        }
        return yandex_device

    async def get_devices(self, request: Request):
        """Возвращает список устройств пользователя."""
        try:
            username = self._get_username_from_request(request)
            request_id = request.headers.get("X-Request-Id", "unknown")
            logger.info(f"[{request_id}] Received GET /v1.0/user/devices for user '{username}'")

            user_devices = self.db.get_user_devices(username)
            yandex_devices = [self._convert_device_to_yandex_format(d) for d in user_devices if d]
            
            response_payload = {
                "request_id": request_id,
                "payload": { "user_id": username, "devices": yandex_devices }
            }
            logger.info(f"[{request_id}] Responding with {len(yandex_devices)} devices for '{username}'")
            return JSONResponse(content=response_payload)
        except Exception as e:
            logger.error(f"Critical error in get_devices: {e}", exc_info=True)
            return JSONResponse(status_code=500, content={"error": "Internal Server Error"})

    async def query_devices(self, request: Request):
        """Возвращает текущее состояние с кэшем"""
        try:
            username = self._get_username_from_request(request)
            request_id = request.headers.get("X-Request-Id", "unknown")
            body = await request.json()

            requested_devices_info = body.get("devices", [])
            device_ids = [d["id"] for d in requested_devices_info]

            # Быстрый путь: сразу отдаём кэшированное состояние из БД
            user_devices = self.db.get_user_devices(username)
            devices_response = []

            for dev_info in requested_devices_info:
                dev_id = dev_info["id"]
                # Ищем устройство в БД
                device = next((d for d in user_devices if d.get("id") == dev_id), None)

                if device and device.get("available", True):
                    devices_response.append({
                        "id": dev_id,
                        "capabilities": [{
                            "type": "devices.capabilities.on_off",
                            "state": {
                                "instance": "on",
                                "value": device.get("state", False)
                            }
                        }]
                    })
                else:
                    devices_response.append({
                        "id": dev_id,
                        "error_code": "DEVICE_UNREACHABLE"
                    })

            # Фоновое обновление состояния через агента (не ждём результата)
            if self.ws_manager.is_connected(username):
                asyncio.create_task(
                    self._refresh_device_states_background(username, device_ids)
                )

            return JSONResponse(content={
                "request_id": request_id,
                "payload": {"devices": devices_response}
            })

        except Exception as e:
            logger.error(f"Error in query_devices: {e}", exc_info=True)
            return JSONResponse(status_code=500, content={"error": "Internal Server Error"})

    async def _refresh_device_states_background(self, username: str, device_ids: List[str]):
        """Фоновое обновление статусов (не блокирует HTTP)"""
        try:
            device_states = await self.ws_manager.request_device_status(
                username, device_ids, timeout=3
            )

            if device_states:
                # Обновляем БД для следующего запроса
                user_devices = self.db.get_user_devices(username)
                for state in device_states:
                    dev_id = state.get("id")
                    for device in user_devices:
                        if device.get("id") == dev_id:
                            device["state"] = state.get("state", False)
                            device["available"] = state.get("available", True)

                self.db.update_user_devices(username, user_devices)
                logger.debug(f"Updated states for {len(device_states)} devices")
        except Exception as e:
            logger.warning(f"Background refresh failed: {e}")

    async def execute_action(self, request: Request):
        """Выполняет команду ОПТИМИСТИЧНО"""
        try:
            username = self._get_username_from_request(request)
            request_id = request.headers.get("X-Request-Id", "unknown")
            body = await request.json()

            devices_to_action = body.get("payload", {}).get("devices", [])

            # Оптимистичный ответ: сразу подтверждаем "DONE" в пределах таймаута Алисы
            devices_response = []
            commands = []

            for device in devices_to_action:
                for cap in device.get("capabilities", []):
                    if cap.get("type") == "devices.capabilities.on_off":
                        new_state = cap["state"]["value"]

                        # Сохраняем в БД немедленно
                        user_devices = self.db.get_user_devices(username)
                        for dev in user_devices:
                            if dev.get("id") == device["id"]:
                                dev["state"] = new_state
                        self.db.update_user_devices(username, user_devices)

                        commands.append({
                            "device_id": device["id"],
                            "actions": [{"type": "on_off", "value": new_state}]
                        })

                # Формируем успешный ответ
                devices_response.append({
                    "id": device["id"],
                    "capabilities": [{
                        "type": cap["type"],
                        "state": {
                            "instance": cap["state"]["instance"],
                            "action_result": {"status": "DONE"}
                        }
                    } for cap in device.get("capabilities", [])]
                })

            # Фоновая доставка команды агенту (не ждём подтверждения)
            if self.ws_manager.is_connected(username):
                asyncio.create_task(
                    self.ws_manager.send_command(username, commands, wait_for_response=False)
                )
                asyncio.create_task(
                    self.ws_manager.send_personal_message(username, {"type": "refresh_ui"})
                )

            return JSONResponse(content={
                "request_id": request_id,
                "payload": {"devices": devices_response}
            })

        except Exception as e:
            logger.error(f"Error in execute_action: {e}", exc_info=True)
            return JSONResponse(status_code=500, content={"error": "Internal Server Error"})

    async def unlink_account(self, request: Request):
        """Отвязывает аккаунт пользователя."""
        try:
            username = self._get_username_from_request(request)
            request_id = request.headers.get("X-Request-Id", "unknown")
            logger.info(f"[{request_id}] Received POST /v1.0/user/unlink for user '{username}'.")
            
            self.db.clear_yandex_token(username)
            return JSONResponse(status_code=200, content={"request_id": request_id})
        except Exception as e:
            logger.error(f"Error in unlink_account: {e}", exc_info=True)
            return JSONResponse(status_code=500, content={"error": "Internal Server Error"})

    def _is_cache_fresh(self, username: str, max_age_seconds: int = 30) -> bool:
        """Проверка свежести кэша"""
        user = self.db.get_user(username)
        if not user or 'devices_updated_at' not in user:
            return False

        updated_at = datetime.fromisoformat(user['devices_updated_at'])
        return (datetime.now() - updated_at).total_seconds() < max_age_seconds