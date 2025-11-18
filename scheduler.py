# scheduler.py - Фоновые задачи и планировщик для LOKAL Cloud
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class BackgroundTasksManager:
    """Менеджер фоновых задач и периодических операций"""
    
    def __init__(self, db_manager, ws_manager):
        self.db = db_manager
        self.ws = ws_manager
        self.scheduler = AsyncIOScheduler()
        self.tasks_stats = {
            "total_executed": 0,
            "total_failed": 0,
            "last_execution": {},
            "execution_times": {}
        }
        
    async def start(self):
        """Запуск планировщика и регистрация задач"""
        from config import settings
        
        if not settings.BACKGROUND_TASKS_ENABLED:
            logger.info("Background tasks disabled")
            return
        
        # Регистрируем задачи
        self._register_tasks()
        
        # Запускаем планировщик
        self.scheduler.start()
        logger.info("Background tasks scheduler started")
    
    async def stop(self):
        """Остановка планировщика"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Background tasks scheduler stopped")
    
    def _register_tasks(self):
        """Регистрация всех фоновых задач"""
        from config import settings
        
        # Очистка БД каждый час
        self.scheduler.add_job(
            self._cleanup_database,
            trigger=IntervalTrigger(hours=settings.CLEANUP_INTERVAL_HOURS),
            id="cleanup_database",
            name="Database Cleanup",
            replace_existing=True
        )
        
        # Резервное копирование каждые 6 часов
        self.scheduler.add_job(
            self._create_database_backup,
            trigger=IntervalTrigger(hours=settings.DB_AUTO_BACKUP_INTERVAL_HOURS),
            id="database_backup",
            name="Database Backup",
            replace_existing=True
        )
        
        # Проверка health WebSocket соединений каждые 5 минут
        self.scheduler.add_job(
            self._check_websocket_health,
            trigger=IntervalTrigger(minutes=5),
            id="websocket_health_check",
            name="WebSocket Health Check",
            replace_existing=True
        )
        
        # Сбор статистики каждые 15 минут
        self.scheduler.add_job(
            self._collect_statistics,
            trigger=IntervalTrigger(minutes=15),
            id="collect_statistics",
            name="Collect Statistics",
            replace_existing=True
        )
        
        # Оптимизация БД каждую ночь в 3:00
        self.scheduler.add_job(
            self._optimize_database,
            trigger=CronTrigger(hour=3, minute=0),
            id="optimize_database",
            name="Optimize Database",
            replace_existing=True
        )
        
        # Очистка старых сессий каждые 30 минут
        self.scheduler.add_job(
            self._cleanup_sessions,
            trigger=IntervalTrigger(minutes=30),
            id="cleanup_sessions",
            name="Cleanup Sessions",
            replace_existing=True
        )
        
        logger.info(f"Registered {len(self.scheduler.get_jobs())} background tasks")
    
    async def _cleanup_database(self):
        """Очистка устаревших данных из БД"""
        task_name = "cleanup_database"
        start_time = datetime.utcnow()
        
        try:
            logger.info(f"Starting task: {task_name}")
            
            # Очистка истекших authorization codes
            expired_codes = self.db.cleanup_expired_codes()
            
            # Очистка истекших сессий
            expired_sessions = self.db.cleanup_expired_sessions()
            
            # Очистка старых audit logs
            from config import settings
            old_logs = self.db.cleanup_old_audit_logs(days=settings.AUDIT_RETENTION_DAYS)
            
            # Обновляем статистику
            self._update_task_stats(task_name, start_time, success=True)
            
            logger.info(
                f"Task {task_name} completed: "
                f"{expired_codes} codes, {expired_sessions} sessions, "
                f"{old_logs} logs cleaned"
            )
            
        except Exception as e:
            logger.error(f"Task {task_name} failed: {e}", exc_info=True)
            self._update_task_stats(task_name, start_time, success=False)
    
    async def _create_database_backup(self):
        """Создание резервной копии БД"""
        task_name = "database_backup"
        start_time = datetime.utcnow()
        
        try:
            logger.info(f"Starting task: {task_name}")
            
            backup_file = self.db.create_backup()
            
            self._update_task_stats(task_name, start_time, success=True)
            
            logger.info(f"Task {task_name} completed: {backup_file}")
            
        except Exception as e:
            logger.error(f"Task {task_name} failed: {e}", exc_info=True)
            self._update_task_stats(task_name, start_time, success=False)
    
    async def _check_websocket_health(self):
        """Проверка здоровья WebSocket соединений"""
        task_name = "websocket_health_check"
        start_time = datetime.utcnow()
        
        try:
            logger.debug(f"Starting task: {task_name}")
            
            stats = self.ws.get_stats()
            active_connections = stats.get('active_connections', 0)
            
            if active_connections > 0:
                logger.info(
                    f"WebSocket health check: {active_connections} active connections, "
                    f"{stats.get('pending_responses', 0)} pending responses"
                )
            
            # Можно добавить проверку на проблемные соединения
            # и автоматическое переподключение
            
            self._update_task_stats(task_name, start_time, success=True)
            
        except Exception as e:
            logger.error(f"Task {task_name} failed: {e}", exc_info=True)
            self._update_task_stats(task_name, start_time, success=False)
    
    async def _collect_statistics(self):
        """Сбор и логирование статистики"""
        task_name = "collect_statistics"
        start_time = datetime.utcnow()
        
        try:
            logger.debug(f"Starting task: {task_name}")
            
            # Собираем статистику из разных источников
            db_stats = self.db.get_stats()
            ws_stats = self.ws.get_stats()
            
            # Логируем для мониторинга
            logger.info(
                f"System stats: "
                f"Users: {db_stats.get('total_users')}, "
                f"Active sessions: {db_stats.get('active_sessions')}, "
                f"WebSocket connections: {ws_stats.get('active_connections')}, "
                f"Total devices: {db_stats.get('total_devices')}"
            )
            
            # Здесь можно отправлять метрики в Prometheus, Grafana и т.д.
            
            self._update_task_stats(task_name, start_time, success=True)
            
        except Exception as e:
            logger.error(f"Task {task_name} failed: {e}", exc_info=True)
            self._update_task_stats(task_name, start_time, success=False)
    
    async def _optimize_database(self):
        """Оптимизация базы данных"""
        task_name = "optimize_database"
        start_time = datetime.utcnow()
        
        try:
            logger.info(f"Starting task: {task_name}")
            
            self.db.optimize_database()
            
            self._update_task_stats(task_name, start_time, success=True)
            
            logger.info(f"Task {task_name} completed")
            
        except Exception as e:
            logger.error(f"Task {task_name} failed: {e}", exc_info=True)
            self._update_task_stats(task_name, start_time, success=False)
    
    async def _cleanup_sessions(self):
        """Очистка истекших сессий"""
        task_name = "cleanup_sessions"
        start_time = datetime.utcnow()
        
        try:
            logger.debug(f"Starting task: {task_name}")
            
            expired_sessions = self.db.cleanup_expired_codes()
            
            if expired_sessions > 0:
                logger.info(f"Cleaned up {expired_sessions} expired sessions")
            
            self._update_task_stats(task_name, start_time, success=True)
            
        except Exception as e:
            logger.error(f"Task {task_name} failed: {e}", exc_info=True)
            self._update_task_stats(task_name, start_time, success=False)
    
    def _update_task_stats(self, task_name: str, start_time: datetime, success: bool):
        """Обновление статистики выполнения задач"""
        execution_time = (datetime.utcnow() - start_time).total_seconds()
        
        if success:
            self.tasks_stats["total_executed"] += 1
        else:
            self.tasks_stats["total_failed"] += 1
        
        self.tasks_stats["last_execution"][task_name] = datetime.utcnow().isoformat()
        
        if task_name not in self.tasks_stats["execution_times"]:
            self.tasks_stats["execution_times"][task_name] = []
        
        self.tasks_stats["execution_times"][task_name].append(execution_time)
        
        # Храним последние 100 выполнений
        if len(self.tasks_stats["execution_times"][task_name]) > 100:
            self.tasks_stats["execution_times"][task_name] = \
                self.tasks_stats["execution_times"][task_name][-100:]
    
    def get_tasks_status(self) -> Dict[str, Any]:
        """Получение статуса всех задач"""
        jobs = self.scheduler.get_jobs()
        
        jobs_info = []
        for job in jobs:
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
            
            task_name = job.id
            last_execution = self.tasks_stats["last_execution"].get(task_name)
            
            # Вычисляем среднее время выполнения
            avg_execution_time = None
            if task_name in self.tasks_stats["execution_times"]:
                times = self.tasks_stats["execution_times"][task_name]
                if times:
                    avg_execution_time = sum(times) / len(times)
            
            jobs_info.append({
                "id": job.id,
                "name": job.name,
                "next_run": next_run,
                "last_execution": last_execution,
                "avg_execution_time_seconds": avg_execution_time
            })
        
        return {
            "total_tasks": len(jobs),
            "total_executed": self.tasks_stats["total_executed"],
            "total_failed": self.tasks_stats["total_failed"],
            "tasks": jobs_info
        }
    
    async def run_task_now(self, task_id: str) -> bool:
        """Запуск задачи немедленно"""
        try:
            job = self.scheduler.get_job(task_id)
            if job:
                job.modify(next_run_time=datetime.utcnow())
                logger.info(f"Task {task_id} scheduled for immediate execution")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to run task {task_id}: {e}")
            return False
