"""
Route initialization and registration
This module handles the registration of all API routes and their namespaces.
"""

from flask_restx import Namespace

def create_namespaces(api):
    """Create API namespaces"""
    return {
        'health': api.namespace('health', description='Health checks'),
        'processes': api.namespace('processes', description='PM2 process operations'),
        'logs': api.namespace('logs', description='Process logs operations')
    }

def register_routes(api, services):
    """
    Register all API routes
    Args:
        api: Flask-RESTX API instance
        services: Dictionary containing service instances
    """
    # Create namespaces
    namespaces = create_namespaces(api)

    # Share API models with all namespaces
    for ns in namespaces.values():
        ns.models = api.models

    # Import route creators
    from .health import create_health_routes
    from .processes import create_process_routes
    from .logs import create_log_routes

    # Register routes with their respective namespaces
    route_creators = {
        'health': create_health_routes,
        'processes': create_process_routes,
        'logs': create_log_routes
    }

    # Create routes for each namespace
    routes = {}
    for name, creator in route_creators.items():
        routes[name] = creator(namespaces[name], services)

    return routes

__all__ = ['register_routes']