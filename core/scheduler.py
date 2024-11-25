# core/scheduler.py

import threading
import time
import logging
import queue
from datetime import datetime
from typing import Dict

class MonitoringTask(threading.Thread):
    def __init__(self, name: str, interval: int, func, logger: logging.Logger):
        super().__init__()
        self.name = name
        self.interval = interval
        self.func = func
        self.logger = logger
        self.stop_event = threading.Event()
        self.daemon = True  # Make thread daemonic so it exits when main thread exits

    def run(self):
        self.logger.info(f"Starting {self.name} task with interval {self.interval}s")
        while not self.stop_event.is_set():
            try:
                self.func()
            except Exception as e:
                self.logger.error(f"Error in {self.name} task: {str(e)}")
            time.sleep(self.interval)

    def stop(self):
        self.logger.info(f"Stopping {self.name} task")
        self.stop_event.set()

class MonitoringScheduler:
    def __init__(self, config, services, logger):
        self.config = config
        self.services = services
        self.logger = logger
        self.tasks: Dict[str, MonitoringTask] = {}
        self.error_queue = queue.Queue()  # Queue to hold errors from background tasks

    def init_scheduler(self):
        """Initialize and start monitoring tasks"""
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

            # Start error monitoring thread
            self._start_error_monitor()

        except Exception as e:
            self.logger.error(f"Failed to initialize scheduler: {str(e)}")
            self.shutdown()
            raise

    def _process_monitor_task(self):
        """Wrapper for process monitoring to capture errors"""
        try:
            self.services['process_manager'].log_status()
        except Exception as e:
            self.error_queue.put(('process_monitor', str(e)))

    def _host_monitor_task(self):
        """Wrapper for host monitoring to capture errors"""
        try:
            self.services['host_monitor'].log_metrics()
        except Exception as e:
            self.error_queue.put(('host_monitor', str(e)))

    def _cleanup_task(self):
        """Wrapper for cleanup task to capture errors"""
        try:
            self._cleanup_old_data()
        except Exception as e:
            self.error_queue.put(('cleanup', str(e)))

    def _cleanup_old_data(self):
        """Clean up old monitoring data"""
        conn = None
        try:
            conn = self.services['db_connection']()
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

    def _start_error_monitor(self):
        """Start thread to monitor for errors from background tasks"""
        def monitor_errors():
            while True:
                try:
                    task_name, error = self.error_queue.get(timeout=1)
                    self.logger.error(f"Error in {task_name}: {error}")
                except queue.Empty:
                    continue
                except Exception as e:
                    self.logger.error(f"Error in error monitor: {str(e)}")

        error_thread = threading.Thread(target=monitor_errors, daemon=True)
        error_thread.start()

    def shutdown(self):
        """Shutdown the scheduler gracefully"""
        self.logger.info("Shutting down monitoring scheduler...")
        for name, task in self.tasks.items():
            try:
                task.stop()
                task.join(timeout=5)  # Give each task 5 seconds to stop
                if task.is_alive():
                    self.logger.warning(f"{name} task did not stop gracefully")
            except Exception as e:
                self.logger.error(f"Error stopping {name} task: {str(e)}")
        self.logger.info("Monitoring scheduler shutdown complete")