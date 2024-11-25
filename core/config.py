# core/config.py
import os
from pathlib import Path

class Config:
    """Application configuration management"""
    
    def __init__(self):
        # Server Configuration
        self.PORT = int(os.environ.get('PORT', 5000))
        self.HOST = os.environ.get('HOST', '0.0.0.0')
        self.DEBUG = False  # Force debug mode on
        
        # Logging Configuration
        self.LOG_LEVEL = 'DEBUG'  # Force debug logging
        self.LOG_FORMAT = '%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
        self.LOG_FILE = os.environ.get('LOG_FILE', 'logs/pm2_controller.log')
        self.LOG_MAX_BYTES = int(os.environ.get('LOG_MAX_BYTES', 10485760))
        self.LOG_BACKUP_COUNT = int(os.environ.get('LOG_BACKUP_COUNT', 5))
        
        # PM2 Configuration
        self.PM2_BIN = os.environ.get('PM2_BIN', 'pm2')
        self.MAX_LOG_LINES = int(os.environ.get('MAX_LOG_LINES', 1000))
        self.COMMAND_TIMEOUT = int(os.environ.get('COMMAND_TIMEOUT', 30))
        self.MAX_RETRIES = int(os.environ.get('MAX_RETRIES', 3))
        self.RETRY_DELAY = int(os.environ.get('RETRY_DELAY', 1))
        
        # File Paths
        self.PM2_CONFIG_DIR = Path('/home/pm2/pm2-configs')
        self.PYTHON_WRAPPER_DIR = Path('/home/pm2/pm2-configs')
        
        self.DB_PATH = os.getenv('DB_PATH', 'monitoring.db')
        # Scheduler intervals (in seconds)
        self.SCHEDULER_PROCESS_INTERVAL = int(os.getenv('SCHEDULER_PROCESS_INTERVAL', 60))  # 1 minute
        self.SCHEDULER_HOST_INTERVAL = int(os.getenv('SCHEDULER_HOST_INTERVAL', 60))       # 1 minute
        self.SCHEDULER_CLEANUP_INTERVAL = int(os.getenv('SCHEDULER_CLEANUP_INTERVAL', 3600)) # 1 hour
        
        # Monitoring settings
        self.MONITORING_RETENTION_DAYS = int(os.getenv('MONITORING_RETENTION_DAYS', 30))
        self.MONITORING_MAX_POINTS = int(os.getenv('MONITORING_MAX_POINTS', 10000))
        
        self._create_required_directories()
    
    def _create_required_directories(self):
        """Create required directories if they don't exist"""
        os.makedirs('logs', exist_ok=True)
        self.PM2_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.PYTHON_WRAPPER_DIR.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def from_env(cls) -> 'Config':
        """Create configuration from environment variables"""
        return cls()