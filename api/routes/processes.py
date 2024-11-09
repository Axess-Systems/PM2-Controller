from datetime import datetime
from flask_restx import Resource, Namespace
from core.exceptions import ProcessNotFoundError, ProcessAlreadyExistsError

def create_process_routes(namespace: Namespace):
    """Create process management routes"""
    
    @namespace.route('/')
    class ProcessList(Resource):
        def __init__(self, api=None, *args, **kwargs):
            super().__init__(api)
            self.pm2_service = kwargs.get('pm2_service')
            self.process_manager = kwargs.get('process_manager')

        @namespace.doc(
            responses={
                200: 'Success',
                500: 'Internal server error'
            }
        )
        def get(self):
            """Get list of all PM2 processes"""
            try:
                return self.pm2_service.list_processes()
            except Exception as e:
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': None
                }, 500

        @namespace.doc(
            responses={
                201: 'Process created',
                400: 'Invalid input',
                409: 'Process already exists',
                500: 'Internal server error'
            }
        )
        def post(self):
            """Create a new PM2 process"""
            try:
                return self.process_manager.create_process(namespace.payload), 201
            except ProcessAlreadyExistsError as e:
                return {
                    'error': str(e),
                    'error_type': 'ProcessAlreadyExistsError',
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': namespace.payload.get('name')}
                }, 409
            except Exception as e:
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': None
                }, 500

    @namespace.route('/<string:process_name>')
    class Process(Resource):
        def __init__(self, api=None, *args, **kwargs):
            super().__init__(api)
            self.pm2_service = kwargs.get('pm2_service')

        @namespace.doc(
            responses={
                200: 'Success',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        def get(self, process_name):
            """Get details of a specific process"""
            try:
                return self.pm2_service.get_process(process_name)
            except ProcessNotFoundError as e:
                return {
                    'error': str(e),
                    'error_type': 'ProcessNotFoundError',
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 404
            except Exception as e:
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': None
                }, 500

        @namespace.doc(
            responses={
                200: 'Process deleted',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        def delete(self, process_name):
            """Delete a specific process"""
            try:
                self.pm2_service.delete_process(process_name)
                return {"message": f"Process {process_name} deleted successfully"}
            except ProcessNotFoundError as e:
                return {
                    'error': str(e),
                    'error_type': 'ProcessNotFoundError',
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 404
            except Exception as e:
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': None
                }, 500

    @namespace.route('/<string:process_name>/<string:action>')
    class ProcessControl(Resource):
        def __init__(self, api=None, *args, **kwargs):
            super().__init__(api)
            self.pm2_service = kwargs.get('pm2_service')

        @namespace.doc(
            responses={
                200: 'Success',
                400: 'Invalid action',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        def post(self, process_name, action):
            """Control a specific process (start/stop/restart/reload)"""
            try:
                if action == 'start':
                    self.pm2_service.start_process(process_name)
                elif action == 'stop':
                    self.pm2_service.stop_process(process_name)
                elif action == 'restart':
                    self.pm2_service.restart_process(process_name)
                elif action == 'reload':
                    self.pm2_service.reload_process(process_name)
                else:
                    return {'error': 'Invalid action'}, 400

                return {"message": f"Process {process_name} {action}ed successfully"}
            except ProcessNotFoundError as e:
                return {
                    'error': str(e),
                    'error_type': 'ProcessNotFoundError',
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 404
            except Exception as e:
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': None
                }, 500