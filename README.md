# Alice-SmartLight — облачный backend умного дома

> **EN (summary).** Cloud half of the **Alice-SmartLight** smart-home system — a real, deployed project.
> A FastAPI service that connects **Yandex Alice** (Smart Home API + OAuth) to a **home agent** running on the
> user's local network over a persistent **WebSocket tunnel**. The cloud never talks to lamps directly: it holds
> a cached device state, answers Alice **optimistically in under ~1.5 s** (inside Alice's request timeout), and
> forwards the real command to the home agent in the background. JWT auth, per-IP rate limiting, security
> middleware and scheduled maintenance jobs included.

---

Облачная половина умного дома **Alice-SmartLight** (реальный проект в проде). Сервис на **FastAPI**, который
соединяет **Яндекс Алису** с домашним агентом пользователя и позволяет управлять устройствами голосом.

Ключевая инженерная задача — уложиться в жёсткий таймаут запроса от Алисы, при том что реальное устройство
находится за домашним роутером (NAT, серый IP) и может отвечать медленно. Решение — **оптимистичные ответы**
поверх постоянного **WebSocket-туннеля** «облако ↔ локальный агент».

## Как это устроено

```
   Голос                Smart Home API            WebSocket-туннель
 ┌────────┐   OAuth   ┌──────────────────┐   постоянное соединение   ┌──────────────┐
 │ Алиса  │──────────▶│  Alice-SmartLight │◀─────────────────────────▶│ Домашний     │
 │ / апп  │  Bearer   │  cloud (FastAPI)  │   ws/agent/{jwt}          │ агент (LAN)  │
 └────────┘◀──────────│                   │──────────────────────────▶└──────┬───────┘
   ответ < ~1.5с      │  кэш состояния,   │   команды в фоне                 │
                      │  JWT, rate-limit  │                                  ▼
                      └──────────────────┘                            реальные устройства
```

1. **OAuth Яндекса.** Пользователь привязывает аккаунт: `/auth` отдаёт форму входа, `/auth/callback` выдаёт
   authorization code, `/auth/token` меняет его на долгоживущий Bearer-токен для Smart Home API.
2. **WebSocket-туннель.** Домашний агент держит постоянное соединение `ws/agent/{jwt}`. Через него облако
   отправляет команды и запрашивает статусы, а агент рапортует об изменениях. Так решается проблема серого IP:
   входящее соединение инициирует именно агент.
3. **Оптимистичные ответы.** На `POST /v1.0/user/devices/action` облако сразу пишет новое состояние в кэш и
   отвечает Алисе `DONE`, **не дожидаясь** дома. Реальная команда уходит агенту фоновой задачей
   (`asyncio.create_task`). За счёт этого ответ укладывается в таймаут Алисы (~1.5 с), даже если дом отвечает
   секунды. На `.../query` тем же приёмом отдаётся кэшированный статус, а фоновое обновление подтягивает
   свежие данные к следующему запросу (см. проверку свежести кэша в `yandex_api.py`).

## Стек

- **FastAPI** + Uvicorn/Gunicorn — HTTP и WebSocket
- **JWT** (python-jose) — авторизация агента и пользователей, access/refresh токены
- **TinyDB** — лёгкое JSON-хранилище пользователей, токенов, сессий
- **APScheduler** — фоновые задачи (бэкапы БД, очистка кодов/сессий, health-check соединений)
- Собственные **middleware**: security-заголовки, rate limiting по IP, сбор метрик, логирование запросов
- **Docker** / docker-compose для деплоя

## Запуск

```bash
# 1. Зависимости
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Конфигурация
cp .env.example .env
# отредактируйте .env: SECRET_KEY, YANDEX_CLIENT_ID/SECRET и т.д.

# 3. Старт
uvicorn main:app --host 0.0.0.0 --port 8000
# Swagger (вне production): http://localhost:8000/docs
```

Через Docker:

```bash
docker compose up -d --build
```

## Структура

| Файл                    | Назначение                                                             |
|-------------------------|------------------------------------------------------------------------|
| `main.py`               | Точка входа FastAPI: эндпоинты auth, OAuth, Smart Home API, WebSocket   |
| `yandex_api.py`         | Обработчик Smart Home API Яндекса (devices/query/action, оптимистично)  |
| `websocket_manager.py`  | Менеджер WS-соединений с агентами: ping/pong, запрос статусов, команды  |
| `auth.py`               | JWT, хеширование паролей, валидация, rate limiter, зависимости FastAPI  |
| `db_manager.py`         | Доступ к TinyDB: пользователи, токены Яндекса, коды авторизации, сессии |
| `middleware.py`         | CORS, security-заголовки, rate limit по IP, метрики, логирование        |
| `scheduler.py`          | Фоновые задачи: бэкапы, очистка, health-check, сбор статистики          |
| `config.py`             | Настройки через pydantic-settings (читаются из `.env`)                  |

## Основные эндпоинты

- `POST /register`, `POST /token`, `POST /refresh` — регистрация и JWT
- `GET /auth`, `POST /auth/callback`, `POST /auth/token` — OAuth-поток Яндекса
- `GET /v1.0/user/devices`, `POST /v1.0/user/devices/query`, `POST /v1.0/user/devices/action` — Smart Home API
- `WS /ws/agent/{token}` — канал к домашнему агенту
- `GET /health`, `GET /admin/stats` — мониторинг

---

## Об авторе

**Ковалик Олег Владиславович** — разработчик (мобильная разработка, backend, блокчейн).

- Чемпионат **«Профессионалы» 2025** — 1 место (Самара) по мобильной разработке, 3 место (Россия),
  1 место в командном зачёте; 2 место (Самара) по блокчейну
- **Волга-IT'2025** — 3 место (Flutter / ОС Аврора)
- **MTS True Tech Champ** — 3 место
- Финалист **РуКод** (МФТИ)
- **1С:Профессионал 8.3**
- Фриланс-контракты по Solidity / FunC / Tact (под NDA)

Проект выполнен в рамках разработки под ключ (студия «Лендвис»).
