from flask import Flask
from flask_restx import Api
from flask_cors import CORS

# Import core modules
from core.config import Config
from core.logging import setup_logging

# Import services
from services.pm2 import PM2Service
from services.process_manager import ProcessManager
from services.log_manager import LogManager

# Import API components
from api.models.process import create_api_models
from api.models.error import create_error_models
from api.routes.processes import create_process_routes
from api.routes.health import create_health_routes
from api.routes.logs import create_log_routes

def create_app():
    """Create and configure the Flask application"""
    # Initialize Flask app
    app = Flask(__name__)
    
    # Initialize API with documentation
    api = Api(app, 
        version='1.0', 
        title='PM2 Controller API',
        description='REST API for controlling PM2 processes',
        doc='/',
        prefix='/api'
    )
    
    # Enable CORS
    CORS(app)
    
    # Load configuration and setup logging
    config = Config()
    logger = setup_logging(config)
    
    # Initialize services
    pm2_service = PM2Service(config, logger)
    process_manager = ProcessManager(config, logger)
    log_manager = LogManager(config, logger)
    
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
    
    # Create services dict for dependency injection
    services = {
        'pm2_service': pm2_service,
        'process_manager': process_manager,
        'log_manager': log_manager,
        'logger': logger,
        'config': config
    }
    
    # Set resource_class_kwargs for each namespace BEFORE creating routes
    processes_ns.resource_class_kwargs = services
    health_ns.resource_class_kwargs = services
    logs_ns.resource_class_kwargs = services
    
    # Register routes
    create_health_routes(health_ns)
    create_process_routes(processes_ns)
    create_log_routes(logs_ns)
    
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