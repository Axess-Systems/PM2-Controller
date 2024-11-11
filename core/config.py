from typing import Dict
import os
from pathlib import Path

class Config:
    """Application configuration management"""
    
    def __init__(self):
        load_dotenv()
        
        # Server Configuration
        self.PORT = int(os.environ.get('PORT', 5000))
        self.HOST = os.environ.get('HOST', '0.0.0.0')
        self.DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
        
        # Logging Configuration
        self.LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
        self.LOG_FORMAT = os.environ.get('LOG_FORMAT', 
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.LOG_FILE = os.environ.get('LOG_FILE', 'logs/pm2_controller.log')
        self.LOG_MAX_BYTES = int(os.environ.get('LOG_MAX_BYTES', 10485760))  # 10MB
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
        
        # Ensure required directories exist
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