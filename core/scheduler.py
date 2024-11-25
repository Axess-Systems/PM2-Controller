# core/scheduler.py

import threading
import time
import sqlite3
from datetime import datetime

class MonitoringScheduler:
    def __init__(self, config, services, logger):
        self.config = config
        self.services = services
        self.logger = logger
        self.stop_flag = threading.Event()
        self.monitoring_thread = None
        self.cleanup_thread = None
        self.host_thread = None

    def init_scheduler(self):
        """Initialize monitoring threads with configurable intervals"""
        try:
            # Process monitoring thread
            self.monitoring_thread = threading.Thread(
                target=self._run_interval,
                args=(
                    self.services['process_manager'].log_status,
                    self.config.SCHEDULER_PROCESS_INTERVAL,
                    'process monitoring'
                )
            )
            self.monitoring_thread.daemon = True
            self.monitoring_thread.start()

            # Host monitoring thread
            self.host_thread = threading.Thread(
                target=self._run_interval,
                args=(
                    self.services['host_monitor'].log_metrics,
                    self.config.SCHEDULER_HOST_INTERVAL,
                    'host monitoring'
                )
            )
            self.host_thread.daemon = True
            self.host_thread.start()

            # Cleanup thread
            self.cleanup_thread = threading.Thread(
                target=self._run_interval,
                args=(
                    self._cleanup_old_data,
                    self.config.SCHEDULER_CLEANUP_INTERVAL,
                    'data cleanup'
                )
            )
            self.cleanup_thread.daemon = True
            self.cleanup_thread.start()

            self.logger.info(
                f"Scheduler started with intervals - Process: {self.config.SCHEDULER_PROCESS_INTERVAL}s, "
                f"Host: {self.config.SCHEDULER_HOST_INTERVAL}s"
            )

        except Exception as e:
            self.logger.error(f"Failed to initialize scheduler: {str(e)}")
            raise

    def _run_interval(self, func, interval, name):
        """Run a function at specified intervals"""
        while not self.stop_flag.is_set():
            try:
                func()
            except Exception as e:
                self.logger.error(f"Error in {name}: {str(e)}")
            time.sleep(interval)

    def _monitoring_loop(self):
        """Main monitoring loop"""
        while not self.stop_flag.is_set():
            try:
                self.services['process_manager'].log_status()
                self.services['host_monitor'].log_metrics()
            except Exception as e:
                self.logger.error(f"Monitoring error: {str(e)}")
            time.sleep(self.config.SCHEDULER_PROCESS_INTERVAL)

    def _cleanup_loop(self):
        """Cleanup loop"""
        while not self.stop_flag.is_set():
            try:
                self._cleanup_old_data()
            except Exception as e:
                self.logger.error(f"Cleanup error: {str(e)}")
            time.sleep(self.config.SCHEDULER_CLEANUP_INTERVAL)

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
            self.logger.info(f"Cleaned up monitoring data older than {retention_days} days")
            
        except Exception as e:
            self.logger.error(f"Error during data cleanup: {str(e)}")
        finally:
            if conn:
                conn.close()

    def shutdown(self):
        """Shutdown the scheduler gracefully"""
        try:
            self.stop_flag.set()
            if self.monitoring_thread:
                self.monitoring_thread.join(timeout=5)
            if self.cleanup_thread:
                self.cleanup_thread.join(timeout=5)
            self.logger.info("Scheduler shutdown successfully")
        except Exception as e:
            self.logger.error(f"Error during scheduler shutdown: {str(e)}")