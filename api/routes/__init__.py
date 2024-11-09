from flask_restx import Namespace
from .health import HealthCheck
from .processes import ProcessList, Process, ProcessControl

def register_routes(api, services):
    """Register all API routes"""
    
    # Create namespaces
    health_ns = api.namespace('health', description='Health checks')
    processes_ns = api.namespace('processes', description='PM2 process operations')

    # Register health routes
    health_ns.add_resource(
        HealthCheck,
        '/',
        resource_class_kwargs={
            'api': api,
            'pm2_service': services['pm2_service']
        }
    )

    # Register process routes
    processes_ns.add_resource(
        ProcessList,
        '/',
        resource_class_kwargs={
            'api': api,
            'pm2_service': services['pm2_service'],
            'process_manager': services['process_manager']
        }
    )

    processes_ns.add_resource(
        Process,
        '/<string:process_name>',
        resource_class_kwargs={
            'api': api,
            'pm2_service': services['pm2_service']
        }
    )

    processes_ns.add_resource(
        ProcessControl,
        '/<string:process_name>/<string:action>',
        resource_class_kwargs={
            'api': api,
            'pm2_service': services['pm2_service']
        }
    )