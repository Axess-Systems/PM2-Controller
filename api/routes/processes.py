from datetime import datetime
from pathlib import Path
import os
import json
import re
import configparser
import subprocess
from flask_restx import Resource
from core.exceptions import ProcessNotFoundError, ProcessAlreadyExistsError

def create_process_routes(namespace):
    """Create process management routes"""
    
    @namespace.route('/')
    class ProcessList(Resource):
        _path = '/'
        
        def __init__(self, api=None, pm2_service=None, process_manager=None, logger=None, config=None, **kwargs):
            super().__init__(api)
            self.pm2_service = pm2_service
            self.process_manager = process_manager
            self.logger = logger
            self.config = config
            
            if not all([self.pm2_service, self.process_manager, self.logger, self.config]):
                raise ValueError("Required services not provided to ProcessList")

        @namespace.doc(
            responses={
                200: 'Success',
                500: 'Internal server error'
            }
        )
        def get(self):
            """Get list of all PM2 processes"""
            try:
                processes = self.pm2_service.list_processes()
                
                # Add config file paths to process details
                for process in processes:
                    try:
                        pm2_config = Path(f"{self.config.PM2_CONFIG_DIR}/{process['name']}.config.js")
                        python_config = Path(f"{self.config.PM2_CONFIG_DIR}/{process['name']}.ini")
                        
                        process['config_files'] = {
                            'pm2_config': str(pm2_config) if pm2_config.exists() else None,
                            'python_config': str(python_config) if python_config.exists() else None
                        }
                    except Exception as e:
                        self.logger.warning(f"Error getting config paths for process {process['name']}: {str(e)}")
                
                return processes
                
            except Exception as e:
                self.logger.error(f"Error getting process list: {str(e)}")
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': {
                        'command': 'pm2 jlist',
                        'error_details': str(e)
                    }
                }, 500

        @namespace.doc(
            responses={
                201: 'Process created',
                400: 'Invalid input',
                409: 'Process already exists',
                500: 'Internal server error'
            }
        )
        @namespace.expect(namespace.models['new_process'])
        def post(self):
            """Create a new PM2 process"""
            try:
                result = self.process_manager.create_process(namespace.payload)
                return result, 201
            except ProcessAlreadyExistsError as e:
                return {
                    'error': str(e),
                    'error_type': 'ProcessAlreadyExistsError',
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': namespace.payload.get('name')}
                }, 409
            except Exception as e:
                self.logger.error(f"Error creating process: {str(e)}")
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': None
                }, 500

    @namespace.route('/<string:process_name>')
    class Process(Resource):
        _path = '/<string:process_name>'
        
        def __init__(self, api=None, pm2_service=None, logger=None, **kwargs):
            super().__init__(api)
            self.pm2_service = pm2_service
            self.logger = logger
            
            if not all([self.pm2_service, self.logger]):
                raise ValueError("Required services not provided to Process")

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

    @namespace.route('/<string:process_name>/start')
    class ProcessStart(Resource):
        _path = '/<string:process_name>/start'
        
        def __init__(self, api=None, pm2_service=None, logger=None, **kwargs):
            super().__init__(api)
            self.pm2_service = pm2_service
            self.logger = logger
            
            if not all([self.pm2_service, self.logger]):
                raise ValueError("Required services not provided to ProcessStart")

        @namespace.doc(
            responses={
                200: 'Process started',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        def post(self, process_name):
            """Start a specific process"""
            try:
                self.pm2_service.start_process(process_name)
                return {"message": f"Process {process_name} started successfully"}
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

    @namespace.route('/<string:process_name>/stop')
    class ProcessStop(Resource):
        _path = '/<string:process_name>/stop'
        
        def __init__(self, api=None, pm2_service=None, logger=None, **kwargs):
            super().__init__(api)
            self.pm2_service = pm2_service
            self.logger = logger
            
            if not all([self.pm2_service, self.logger]):
                raise ValueError("Required services not provided to ProcessStop")

        @namespace.doc(
            responses={
                200: 'Process stopped',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        def post(self, process_name):
            """Stop a specific process"""
            try:
                self.pm2_service.stop_process(process_name)
                return {"message": f"Process {process_name} stopped successfully"}
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

    @namespace.route('/<string:process_name>/restart')
    class ProcessRestart(Resource):
        _path = '/<string:process_name>/restart'
        
        def __init__(self, api=None, pm2_service=None, logger=None, **kwargs):
            super().__init__(api)
            self.pm2_service = pm2_service
            self.logger = logger
            
            if not all([self.pm2_service, self.logger]):
                raise ValueError("Required services not provided to ProcessRestart")

        @namespace.doc(
            responses={
                200: 'Process restarted',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        def post(self, process_name):
            """Restart a specific process"""
            try:
                self.pm2_service.restart_process(process_name)
                return {"message": f"Process {process_name} restarted successfully"}
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

    return {
        'ProcessList': ProcessList,
        'Process': Process,
        'ProcessStart': ProcessStart,
        'ProcessStop': ProcessStop,
        'ProcessRestart': ProcessRestart
    }