from datetime import datetime
from flask_restx import Resource, Namespace

def create_health_routes(namespace: Namespace, services):
    """Create health check routes"""
    
    error_model = namespace.models['error']
    
    @namespace.route('/')
    class HealthCheck(Resource):
        def __init__(self, api=None, *args, **kwargs):
            super().__init__(api)
            self.pm2_service = services['pm2_service']
            self.logger = services['logger']

        @namespace.doc(
            responses={
                200: 'Service is healthy',
                500: ('Service is unhealthy', error_model)
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