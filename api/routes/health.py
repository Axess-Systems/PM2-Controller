from datetime import datetime
from flask_restx import Resource

class HealthCheck(Resource):
    def __init__(self, api, pm2_service):
        super().__init__()
        self.api = api
        self.pm2_service = pm2_service
        
        # Setup route documentation
        self.get.__doc__ = "Check service health status"
        self.get = self.api.doc(responses={
            200: 'Service is healthy',
            500: 'Service is unhealthy'
        })(self.get)

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
            return {
                'error': 'Service is unhealthy',
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': str(e)
            }, 500