# core/scheduler.py

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import atexit
import logging

class MonitoringScheduler:
    """Scheduler for monitoring tasks"""
    
    def __init__(self, config, services, logger):
        self.config = config
        self.services = services
        self.logger = logger
        self.scheduler = None

    def init_scheduler(self):
        """Initialize and start the scheduler"""
        try:
            self.scheduler = BackgroundScheduler()
            
            # Add process monitoring job - every minute
            self.scheduler.add_job(
                func=self.services['process_manager'].log_status,
                trigger=IntervalTrigger(seconds=self.config.SCHEDULER_PROCESS_INTERVAL),
                id='process_monitor',
                name='Process Monitoring',
                replace_existing=True,
                max_instances=1,
                coalesce=True  # Combine missed runs
            )
            
            # Add host monitoring job - every minute
            self.scheduler.add_job(
                func=self.services['host_monitor'].log_metrics,
                trigger=IntervalTrigger(seconds=self.config.SCHEDULER_HOST_INTERVAL),
                id='host_monitor',
                name='Host Monitoring',
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            
            # Add cleanup job - every hour
            self.scheduler.add_job(
                func=self._cleanup_old_data,
                trigger=IntervalTrigger(seconds=self.config.SCHEDULER_CLEANUP_INTERVAL),
                id='data_cleanup',
                name='Data Cleanup',
                replace_existing=True,
                max_instances=1
            )
            
            # Start the scheduler
            self.scheduler.start()
            
            # Register shutdown handler
            atexit.register(self.shutdown)
            
            self.logger.info(
                f"Scheduler started successfully. Process interval: {self.config.SCHEDULER_PROCESS_INTERVAL}s, "
                f"Host interval: {self.config.SCHEDULER_HOST_INTERVAL}s"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to initialize scheduler: {str(e)}")
            raise

    def _cleanup_old_data(self):
        """Clean up old monitoring data"""
        try:
            conn = sqlite3.connect(self.config.DB_PATH)
            cursor = conn.cursor()
            retention_days = self.config.MONITORING_RETENTION_DAYS
            
            # Cleanup old process monitoring data
            cursor.execute('''
                DELETE FROM service_status 
                WHERE timestamp < datetime('now', ? || ' days')
            ''', (f'-{retention_days}',))
            
            # Cleanup old host monitoring data
            cursor.execute('''
                DELETE FROM host_metrics 
                WHERE timestamp < datetime('now', ? || ' days')
            ''', (f'-{retention_days}',))
            
            cursor.execute('''
                DELETE FROM disk_metrics 
                WHERE timestamp < datetime('now', ? || ' days')
            ''', (f'-{retention_days}',))
            
            cursor.execute('''
                DELETE FROM network_metrics 
                WHERE timestamp < datetime('now', ? || ' days')
            ''', (f'-{retention_days}',))
            
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
            if self.scheduler:
                self.scheduler.shutdown()
                self.logger.info("Scheduler shutdown successfully")
        except Exception as e:
            self.logger.error(f"Error during scheduler shutdown: {str(e)}")