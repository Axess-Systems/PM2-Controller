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
from services.pm2.service import PM2Service 
from services.process.manager import ProcessManager
from services.log_manager import LogManager
from api.models.process import create_api_models
from api.models.error import create_error_models
from api.routes.processes import create_process_routes
from api.routes.health import create_health_routes
from api.routes.logs import create_log_routes

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

# Check venv before importing any other modules
ensure_venv()

def create_app():
    """Create and configure the Flask application"""
    # Initialize Flask app
    app = Flask(__name__)
    
    # Enable proxy support
    app.wsgi_app = ProxyFix(app.wsgi_app)
    
    # Initialize API
    api = Api(app, 
        version='1.0', 
        title='PM2 Controller API',
        description='REST API for controlling PM2 processes',
        doc='/',
        prefix='/api'
    )
    
    # Configure CORS - single configuration for both API and Swagger UI
    CORS(app, resources={
        r"/*": {  # This covers both /api/* and Swagger UI
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "expose_headers": ["Content-Type"],
            "supports_credentials": True,
            "max_age": 600
        }
    })
    
    # Add security headers and ensure single CORS header
    @app.after_request
    def add_security_headers(response):
        # Remove any existing CORS headers to prevent duplicates
        response.headers.pop('Access-Control-Allow-Origin', None)
        response.headers.pop('Access-Control-Allow-Headers', None)
        response.headers.pop('Access-Control-Allow-Methods', None)
        
        # Add single CORS header
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET, PUT, POST, DELETE, OPTIONS'
        
        # Add security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        return response
    
    # Load configuration and setup logging
    config = Config()
    logger = setup_logging(config)
    
    # Initialize services
    pm2_service = PM2Service(config, logger)
    process_manager = ProcessManager(config, logger)
    log_manager = LogManager(config, logger)
    
    # Create services dict
    services = {
        'pm2_service': pm2_service,
        'process_manager': process_manager,
        'log_manager': log_manager,
        'logger': logger,
        'config': config
    }
    
    # Create namespaces
    health_ns = api.namespace('health', description='Health checks')
    processes_ns = api.namespace('processes', description='PM2 process operations')
    logs_ns = api.namespace('logs', description='Process logs operations')
    
    # Register models
    models = create_api_models(api)
    for name, model in models.items():
        api.models[name] = model
    api.models['error'] = create_error_models(api)
    
    # Share models with namespaces
    for ns in [health_ns, processes_ns, logs_ns]:
        ns.models = api.models
    
    # Register routes with services
    create_process_routes(processes_ns, services)
    create_health_routes(health_ns, services)
    create_log_routes(logs_ns, services)
    
    return app

# This is our application for gunicorn
application = create_app()

if __name__ == '__main__':
    config = Config()
    logger = setup_logging(config)
    logger.info("Starting PM2 Controller API")
    application.run(
        host=config.HOST,
        port=config.PORT,
    )