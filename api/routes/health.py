from datetime import datetime
from flask_restx import Resource

def create_health_routes(namespace):
    """Create health check routes"""
    
    @namespace.route('/')
    class HealthCheck(Resource):
        _path = '/'  # Add path information
        
        def __init__(self, api=None, pm2_service=None, logger=None, **kwargs):
            super().__init__(api)
            self.pm2_service = pm2_service
            self.logger = logger
            
            if not self.pm2_service or not self.logger:
                raise ValueError("Required services not provided: pm2_service and logger are required")

        @namespace.doc(
            responses={
                200: 'Service is healthy',
                500: 'Service is unhealthy'
            }
        )
        def get(self):
            """Check service health status"""
            try:
                # Check PM2 daemon status
                self.pm2_service.execute_command('ping', retry=False)
                
                return {
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "version": "1.0"
                }
            except Exception as e:
                self.logger.error(f"Health check failed: {str(e)}")
                return {
                    'error': 'Service is unhealthy',
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': str(e)
                }, 500

    return {'HealthCheck': HealthCheck}