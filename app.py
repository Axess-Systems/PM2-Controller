from flask import Flask
from flask_restx import Api
from flask_cors import CORS

from core.config import Config
from core.logging import setup_logging
from services.pm2 import PM2Service
from services.process_manager import ProcessManager
from services.log_manager import LogManager
from api.models.process import create_api_models
from api.models.error import create_error_models
from api.routes import register_routes

def create_app() -> Flask:
    """Create and configure the Flask application"""
    # Load configuration
    config = Config.from_env()
    
    # Setup logging
    logger = setup_logging(config)
    
    # Initialize Flask app
    app = Flask(__name__)
    
    # Initialize API
    api = Api(app, 
        version='1.0', 
        title='PM2 Controller API',
        description='REST API for controlling PM2 processes',
        doc='/',
        prefix='/api'
    )
    
    # Enable CORS
    CORS(app)
    
    # Create API models
    api.models.update(create_api_models(api))
    api.models['error'] = create_error_models(api)
    
    # Initialize services
    services = {
        'pm2_service': PM2Service(config, logger),
        'process_manager': ProcessManager(config, logger),
        'log_manager': LogManager(config, logger)
    }
    
    # Register routes
    register_routes(api, services)
    
    return app

if __name__ == '__main__':
    app = create_app()
    config = Config.from_env()
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