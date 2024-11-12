import os
import sys
import subprocess
from pathlib import Path

def ensure_venv():
    """Ensure we're running inside the virtual environment"""
    # Get the directory containing the current script
    current_dir = Path(__file__).parent.absolute()
    venv_path = current_dir / "venv"
    venv_python = venv_path / "bin" / "python"

    # Check if we're already in the virtual environment
    in_venv = sys.prefix != sys.base_prefix

    if not in_venv:
        if not venv_path.exists():
            print(f"Virtual environment not found at {venv_path}")
            sys.exit(1)
        
        if not venv_python.exists():
            print(f"Python interpreter not found at {venv_python}")
            sys.exit(1)

        # Re-execute the script with the virtual environment's Python
        os.execv(str(venv_python), [str(venv_python), __file__] + sys.argv[1:])

# Check venv before importing any other modules
ensure_venv()

from flask import Flask
from flask_restx import Api
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from core.config import Config
from core.logging import setup_logging
from services.pm2 import PM2Service
from services.process_manager import ProcessManager
from services.log_manager import LogManager
from api.models.process import create_api_models
from api.models.error import create_error_models
from api.routes.processes import create_process_routes
from api.routes.health import create_health_routes
from api.routes.logs import create_log_routes

def create_app():
    """Create and configure the Flask application"""
    # Initialize Flask app
    app = Flask(__name__)
    
    # Enable proxy support
    app.wsgi_app = ProxyFix(app.wsgi_app)
    
    # Configure CORS
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
            "expose_headers": ["Content-Type"],
            "supports_credentials": True,
            "max_age": 600
        }
    })
    
    # Initialize API with CORS enabled
    api = Api(app, 
        version='1.0', 
        title='PM2 Controller API',
        description='REST API for controlling PM2 processes',
        doc='/',
        prefix='/api'
    )
    
    # Add CORS headers to Swagger UI
    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
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

def main():
    app = create_app()
    config = Config()
    logger = setup_logging(config)
    
    try:
        logger.info("Starting PM2 Controller API")
        app.run(
            host=config.HOST,
            port=config.PORT,
            debug=config.DEBUG
        )
    except Exception as e:
        logger.error(f"Service startup failed: {str(e)}")
        raise

if __name__ == '__main__':
    main()