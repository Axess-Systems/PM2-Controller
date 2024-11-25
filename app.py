# app.py
import os
import sys
from pathlib import Path
from flask import Flask
from flask_restx import Api
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from core.config import Config
from core.logging import setup_logging
from core.database import setup_database
from core.scheduler import MonitoringScheduler
from services.pm2.service import PM2Service 
from services.process.manager import ProcessManager
from services.log_manager import LogManager
from services.host.monitor import HostMonitor
from api.models.process import create_api_models
from api.models.error import create_error_models
from api.models.host import create_host_models
from api.routes.processes import create_process_routes
from api.routes.health import create_health_routes
from api.routes.logs import create_log_routes
from api.routes.host import create_host_routes

def ensure_venv():
    """Ensure we're running inside the virtual environment"""
    current_dir = Path(__file__).parent.absolute()
    venv_path = current_dir / "venv"
    venv_python = venv_path / "bin" / "python"

    in_venv = sys.prefix != sys.base_prefix

    if not in_venv:
        if not venv_path.exists():
            print(f"Virtual environment not found at {venv_path}")
            sys.exit(1)
        
        if not venv_python.exists():
            print(f"Python interpreter not found at {venv_python}")
            sys.exit(1)

        os.execv(str(venv_python), [str(venv_python), __file__] + sys.argv[1:])

ensure_venv()

def create_app():
    """Create and configure the Flask application"""
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app)
    
    # Load configuration and setup logging
    config = Config()
    logger = setup_logging(config)
    
    # Setup database
    db_connection = setup_database(config)
    logger.info("Database initialized successfully")
    
    # Initialize API
    api = Api(app, 
        version='1.0', 
        title='PM2 Controller API',
        description='REST API for controlling PM2 processes and monitoring system resources',
        doc='/',
        prefix='/api'
    )
    
    # Configure CORS
    CORS(app, resources={
        r"/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "expose_headers": ["Content-Type"],
            "supports_credentials": True,
            "max_age": 600
        }
    })
    
    @app.after_request
    def add_security_headers(response):
        response.headers.pop('Access-Control-Allow-Origin', None)
        response.headers.pop('Access-Control-Allow-Headers', None)
        response.headers.pop('Access-Control-Allow-Methods', None)
        
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET, PUT, POST, DELETE, OPTIONS'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        return response
    
    # Initialize services with database connection
    services = {
        'pm2_service': PM2Service(config, logger),
        'process_manager': ProcessManager(config, logger),
        'log_manager': LogManager(config, logger),
        'host_monitor': HostMonitor(config, logger),
        'logger': logger,
        'config': config,
        'db_connection': db_connection
    }
    
    # Create namespaces
    namespaces = {
        'health': api.namespace('health', description='Health checks'),
        'processes': api.namespace('processes', description='PM2 process operations'),
        'logs': api.namespace('logs', description='Process logs operations'),
        'host': api.namespace('host', description='Host system monitoring')
    }
    
    # Register models
    models = {
        **create_api_models(api),
        'error': create_error_models(api),
        **create_host_models(api)
    }
    
    for name, model in models.items():
        api.models[name] = model
    
    # Share models with namespaces
    for ns in namespaces.values():
        ns.models = api.models
    
    # Register routes
    create_process_routes(namespaces['processes'], services)
    create_health_routes(namespaces['health'], services)
    create_log_routes(namespaces['logs'], services)
    create_host_routes(namespaces['host'], services)

    # Initialize and start monitoring scheduler
    scheduler = MonitoringScheduler(config, services, logger)
    try:
        scheduler.init_scheduler()
        app.scheduler = scheduler
    except Exception as e:
        logger.error(f"Failed to initialize scheduler: {str(e)}")
        # Continue running the app even if scheduler fails

    @app.teardown_appcontext
    def cleanup(exception=None):
        """Cleanup on application shutdown"""
        # Shutdown scheduler if it exists
        if hasattr(app, 'scheduler'):
            try:
                app.scheduler.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down scheduler: {str(e)}")
        
        # Close database connections
        try:
            if db_connection:
                db_connection.close_all()
        except Exception as e:
            logger.error(f"Error closing database connections: {str(e)}")

    @app.errorhandler(Exception)
    def handle_error(e):
        """Global error handler"""
        logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
        return {
            'error': str(e),
            'error_type': type(e).__name__,
            'timestamp': datetime.now().isoformat()
        }, 500

    return app


application = create_app()

if __name__ == '__main__':
    config = Config()
    logger = setup_logging(config)
    logger.info("Starting PM2 Controller API")
    application.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG
    )