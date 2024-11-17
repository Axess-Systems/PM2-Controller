# core/config.py
class Config:
    """Application configuration management"""
    
    def __init__(self):
        # Server Configuration
        self.PORT = int(os.environ.get('PORT', 5000))
        self.HOST = os.environ.get('HOST', '0.0.0.0')
        self.DEBUG = True  # Force debug mode on
        
        # Logging Configuration
        self.LOG_LEVEL = 'DEBUG'  # Force debug logging
        self.LOG_FORMAT = '%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
        self.LOG_FILE = os.environ.get('LOG_FILE', 'logs/pm2_controller.log')
        self.LOG_MAX_BYTES = int(os.environ.get('LOG_MAX_BYTES', 10485760))
        self.LOG_BACKUP_COUNT = int(os.environ.get('LOG_BACKUP_COUNT', 5))
        
        # PM2 Configuration with debug flags
        self.PM2_BIN = os.environ.get('PM2_BIN', 'pm2')
        self.MAX_LOG_LINES = int(os.environ.get('MAX_LOG_LINES', 1000))
        self.COMMAND_TIMEOUT = int(os.environ.get('COMMAND_TIMEOUT', 30))
        self.MAX_RETRIES = int(os.environ.get('MAX_RETRIES', 3))
        self.RETRY_DELAY = int(os.environ.get('RETRY_DELAY', 1))
        
        # File Paths
        self.PM2_CONFIG_DIR = Path('/home/pm2/pm2-configs')
        self.PYTHON_WRAPPER_DIR = Path('/home/pm2/pm2-configs')
        
        self._create_required_directories()

