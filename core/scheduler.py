# core/scheduler.py

import threading
import time
import logging
import queue
import signal
from datetime import datetime
from typing import Dict

class MonitoringTask(threading.Thread):
    def __init__(self, name: str, interval: int, func, logger: logging.Logger):
        super().__init__(name=name)
        self.interval = interval
        self.func = func
        self.logger = logger
        self._stop_event = threading.Event()
        self._running = threading.Event()
        self.daemon = True
        
    def run(self):
        self._running.set()
        self.logger.info(f"Starting {self.name} task with interval {self.interval}s")
        while self._running.is_set() and not self._stop_event.is_set():
            try:
                self.func()
            except Exception as e:
                self.logger.error(f"Error in {self.name} task: {str(e)}")
            
            # Use wait with timeout to allow clean interruption
            self._stop_event.wait(timeout=self.interval)

    def stop(self):
        """Stop the task gracefully"""
        self.logger.info(f"Stopping {self.name} task")
        self._running.clear()
        self._stop_event.set()

class MonitoringScheduler:
    def __init__(self, config, services, logger):
        self.config = config
        self.services = services
        self.logger = logger
        self.tasks: Dict[str, MonitoringTask] = {}
        self._shutdown = False
        self._lock = threading.Lock()

    def init_scheduler(self):
        """Initialize and start monitoring tasks"""
        with self._lock:
            if self._shutdown:
                return
                
            try:
                # Process monitoring task
                self.tasks['process'] = MonitoringTask(
                    name='Process Monitor',
                    interval=self.config.SCHEDULER_PROCESS_INTERVAL,
                    func=self._process_monitor_task,
                    logger=self.logger
                )

                # Host monitoring task
                self.tasks['host'] = MonitoringTask(
                    name='Host Monitor',
                    interval=self.config.SCHEDULER_HOST_INTERVAL,
                    func=self._host_monitor_task,
                    logger=self.logger
                )

                # Data cleanup task
                self.tasks['cleanup'] = MonitoringTask(
                    name='Data Cleanup',
                    interval=self.config.SCHEDULER_CLEANUP_INTERVAL,
                    func=self._cleanup_task,
                    logger=self.logger
                )

                # Start all tasks
                for task in self.tasks.values():
                    task.start()

                self.logger.info("Monitoring scheduler initialized successfully")

            except Exception as e:
                self.logger.error(f"Failed to initialize scheduler: {str(e)}")
                self.shutdown()
                raise

    def _process_monitor_task(self):
        """Process monitoring task"""
        if not self._shutdown:
            try:
                self.services['process_manager'].log_status()
            except Exception as e:
                self.logger.error(f"Process monitoring error: {str(e)}")

    def _host_monitor_task(self):
        """Host monitoring task"""
        if not self._shutdown:
            try:
                self.services['host_monitor'].log_metrics()
            except Exception as e:
                self.logger.error(f"Host monitoring error: {str(e)}")

    def _cleanup_task(self):
        """Database cleanup task"""
        if not self._shutdown:
            try:
                self._cleanup_old_data()
            except Exception as e:
                self.logger.error(f"Cleanup error: {str(e)}")

    def _cleanup_old_data(self):
        """Clean up old monitoring data"""
        conn = None
        try:
            conn = sqlite3.connect(self.config.DB_PATH)
            cursor = conn.cursor()
            retention_days = self.config.MONITORING_RETENTION_DAYS

            tables = ['service_status', 'host_metrics', 'disk_metrics', 'network_metrics']
            for table in tables:
                cursor.execute(
                    f'DELETE FROM {table} WHERE timestamp < datetime("now", ? || " days")',
                    (f'-{retention_days}',)
                )

            conn.commit()
            self.logger.debug(f"Cleaned up monitoring data older than {retention_days} days")

        except Exception as e:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def shutdown(self):
        """Shutdown the scheduler gracefully"""
        with self._lock:
            if self._shutdown:
                return
                
            self._shutdown = True
            self.logger.info("Shutting down monitoring scheduler...")
            
            # Stop all tasks
            for task in self.tasks.values():
                try:
                    task.stop()
                    task.join(timeout=1)  # Reduced timeout to 1 second
                except Exception as e:
                    self.logger.error(f"Error stopping {task.name}: {str(e)}")

            self.tasks.clear()
            self.logger.info("Monitoring scheduler shutdown complete")

    def __del__(self):
        """Ensure cleanup on deletion"""
        self.shutdown()