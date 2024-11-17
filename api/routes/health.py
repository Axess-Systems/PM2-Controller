# api/routes/health.py
from flask_restx import Resource, fields
from services.pm2.service import PM2Service
import logging
from typing import Dict

def create_health_routes(api, services: Dict):
    """Create health check routes with improved error handling"""
    
    # Get services
    pm2_service: PM2Service = services['pm2_service']
    logger: logging.Logger = services['logger']
    
    # Create health check response model
    health_model = api.model('HealthCheck', {
        'status': fields.String(description='API status', example='ok'),
        'version': fields.String(description='API version', example='1.0'),
        'pm2_status': fields.String(description='PM2 daemon status', example='online'),
        'processes': fields.Integer(description='Number of running processes', example=3)
    })
    
    @api.route('')
    class HealthCheck(Resource):
        @api.doc('health_check')
        @api.marshal_with(health_model)
        @api.response(200, 'Success')
        @api.response(500, 'Internal Server Error')
        def get(self):
            """Get system health status"""
            try:
                # Check PM2 daemon status
                processes = pm2_service.list_processes()
                
                running_count = sum(1 for p in processes 
                                  if p.get('pm2_env', {}).get('status') == 'online')
                
                return {
                    'status': 'ok',
                    'version': '1.0',
                    'pm2_status': 'online',
                    'processes': running_count
                }
                
            except Exception as e:
                logger.error(f"Health check failed: {str(e)}", exc_info=True)
                api.abort(500, f"Health check failed: {str(e)}")