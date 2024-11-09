from datetime import datetime
from flask_restx import Resource
from core.exceptions import ProcessNotFoundError, ProcessAlreadyExistsError

class ProcessList(Resource):
    def __init__(self, api, pm2_service, process_manager):
        super().__init__()
        self.api = api
        self.pm2_service = pm2_service
        self.process_manager = process_manager
        
        # Setup route documentation
        self.get.__doc__ = "Get list of all PM2 processes"
        self.get = self.api.doc(responses={
            200: 'Success',
            500: 'Internal server error'
        })(self.get)
        
        self.post.__doc__ = "Create a new PM2 process"
        self.post = self.api.doc(responses={
            201: 'Process created',
            400: 'Invalid input',
            409: 'Process already exists',
            500: 'Internal server error'
        })(self.post)

    def get(self):
        try:
            return self.pm2_service.list_processes()
        except Exception as e:
            return {
                'error': str(e),
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': None
            }, 500

    def post(self):
        try:
            return self.process_manager.create_process(self.api.payload), 201
        except ProcessAlreadyExistsError as e:
            return {
                'error': str(e),
                'error_type': 'ProcessAlreadyExistsError',
                'timestamp': datetime.now().isoformat(),
                'details': {'process_name': self.api.payload.get('name')}
            }, 409
        except Exception as e:
            return {
                'error': str(e),
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': None
            }, 500

class Process(Resource):
    def __init__(self, api, pm2_service):
        super().__init__()
        self.api = api
        self.pm2_service = pm2_service
        
        # Setup route documentation
        self.get.__doc__ = "Get details of a specific process"
        self.get = self.api.doc(responses={
            200: 'Success',
            404: 'Process not found',
            500: 'Internal server error'
        })(self.get)
        
        self.delete.__doc__ = "Delete a specific process"
        self.delete = self.api.doc(responses={
            200: 'Process deleted',
            404: 'Process not found',
            500: 'Internal server error'
        })(self.delete)

    def get(self, process_name):
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

    def delete(self, process_name):
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

class ProcessControl(Resource):
    def __init__(self, api, pm2_service):
        super().__init__()
        self.api = api
        self.pm2_service = pm2_service
        
        # Setup route documentation
        self.post.__doc__ = "Control a specific process (start/stop/restart/reload)"
        self.post = self.api.doc(responses={
            200: 'Success',
            404: 'Process not found',
            500: 'Internal server error'
        })(self.post)

    def post(self, process_name, action):
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