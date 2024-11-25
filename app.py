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
    
    config = Config()
    logger = setup_logging(config)
    
    # Setup database
    from core.database import setup_database
    setup_database(config)
    
    
    api = Api(app, 
        version='1.0', 
        title='PM2 Controller API',
        description='REST API for controlling PM2 processes and monitoring system resources',
        doc='/',
        prefix='/api'
    )
    
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
    
    config = Config()
    logger = setup_logging(config)
    
    services = {
        'pm2_service': PM2Service(config, logger),
        'process_manager': ProcessManager(config, logger),
        'log_manager': LogManager(config, logger),
        'host_monitor': HostMonitor(config, logger),
        'logger': logger,
        'config': config
    }
    
    namespaces = {
        'health': api.namespace('health', description='Health checks'),
        'processes': api.namespace('processes', description='PM2 process operations'),
        'logs': api.namespace('logs', description='Process logs operations'),
        'host': api.namespace('host', description='Host system monitoring')
    }
    
    models = {
        **create_api_models(api),
        'error': create_error_models(api),
        **create_host_models(api)
    }
    
    for name, model in models.items():
        api.models[name] = model
    
    for ns in namespaces.values():
        ns.models = api.models
    
    create_process_routes(namespaces['processes'], services)
    create_health_routes(namespaces['health'], services)
    create_log_routes(namespaces['logs'], services)
    create_host_routes(namespaces['host'], services)

    # Initialize scheduler
    scheduler = MonitoringScheduler(config, services, logger)
    scheduler.init_scheduler()
    app.scheduler = scheduler

    @app.teardown_appcontext
    def cleanup(exception=None):
        if hasattr(app, 'scheduler'):
            app.scheduler.shutdown()

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