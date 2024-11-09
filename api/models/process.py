from datetime import datetime
from pathlib import Path
import os
import json
import re
import configparser
import subprocess
from flask_restx import Resource, Namespace
from core.exceptions import ProcessNotFoundError, ProcessAlreadyExistsError
from core.config import Config

def create_process_routes(namespace: Namespace, services):
    process_model = namespace.models['process']
    error_model = namespace.models['error']
    new_process_model = namespace.models['new_process']

    @namespace.route('/')
    class ProcessList(Resource):
        def __init__(self, api=None, *args, **kwargs):
            super().__init__(api)
            self.pm2_service = kwargs.get('pm2_service')
            self.process_manager = kwargs.get('process_manager')

        @namespace.doc(
            responses={
                200: ('Success', [process_model]),
                500: ('Internal server error', error_model)
            }
        )
        @namespace.marshal_list_with(process_model)
        def get(self):
            """Get list of all PM2 processes"""
            try:
                processes = self.pm2_service.list_processes()
                
                # Add config file paths to process details
                for process in processes:
                    try:
                        pm2_config = Path(f"/home/pm2/pm2-configs/{process['name']}.config.js")
                        python_config = Path(f"/home/pm2/pm2-configs/{process['name']}.ini")
                        
                        process['config_files'] = {
                            'pm2_config': str(pm2_config) if pm2_config.exists() else None,
                            'python_config': str(python_config) if python_config.exists() else None
                        }
                    except Exception as e:
                        services.logger.warning(f"Error getting config paths for process {process['name']}: {str(e)}")
                
                return processes
                
            except Exception as e:
                services.logger.error(f"Error getting process list: {str(e)}")
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
                201: ('Process created', process_model),
                400: ('Invalid input', error_model),
                409: ('Process already exists', error_model),
                500: ('Internal server error', error_model)
            }
        )
        @namespace.expect(new_process_model)
        def post(self):
            """Create a new PM2 process"""
            return self.process_manager.create_process(namespace.payload)

    @namespace.route('/<string:process_name>')
    class Process(Resource):
        def __init__(self, api=None, *args, **kwargs):
            super().__init__(api)
            self.pm2_service = kwargs.get('pm2_service')

        @namespace.doc(
            responses={
                200: ('Success', process_model),
                404: ('Process not found', error_model),
                500: ('Internal server error', error_model)
            }
        )
        @namespace.marshal_with(process_model)
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
                404: ('Process not found', error_model),
                500: ('Internal server error', error_model)
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

    @namespace.route('/<string:process_name>/config')
    class ProcessConfig(Resource):
        def __init__(self, api=None, *args, **kwargs):
            super().__init__(api)
            self.pm2_service = kwargs.get('pm2_service')
            
            # Define config update models
            self.pm2_config_update = namespace.model('PM2ConfigUpdate', {
                'instances': namespace.Integer(description='Number of instances'),
                'cron_restart': namespace.String(description='Cron pattern for restart'),
                'watch': namespace.Boolean(description='Enable watch mode'),
                'autorestart': namespace.Boolean(description='Enable auto-restart')
            })

            self.python_config_update = namespace.model('PythonConfigUpdate', {
                'repository': namespace.Nested(namespace.model('RepositoryUpdate', {
                    'url': namespace.String(description='GitHub repository URL'),
                    'project_dir': namespace.String(description='Project directory name'),
                    'branch': namespace.String(description='Git branch name')
                })),
                'dependencies': namespace.Nested(namespace.model('DependenciesUpdate', {
                    'requirements_file': namespace.String(description='Path to requirements.txt'),
                    'run_script': namespace.String(description='Python script to run'),
                    'arguments': namespace.String(description='Additional script arguments')
                })),
                'variables': namespace.Raw(description='Environment variables'),
                'smtp': namespace.Nested(namespace.model('SMTPUpdate', {
                    'enabled': namespace.Boolean(description='Enable SMTP')
                })),
                'citrix_customer_api': namespace.Nested(namespace.model('CitrixCustomerAPIUpdate', {
                    'enabled': namespace.Boolean(description='Enable Citrix Customer API'),
                    'customers': namespace.List(namespace.String, description='List of customers')
                }))
            })

        @namespace.doc(
            responses={
                200: 'Config files retrieved successfully',
                404: ('Process not found', error_model),
                500: ('Internal server error', error_model)
            }
        )
        def get(self, process_name):
            """Get configuration files for a process"""
            return self.pm2_service.get_process_config(process_name)

        @namespace.doc(
            responses={
                200: 'Config updated successfully',
                404: ('Process not found', error_model),
                500: ('Internal server error', error_model)
            }
        )
        @namespace.expect(namespace.model('ConfigUpdate', {
            'pm2_config': namespace.Nested(pm2_config_update),
            'python_config': namespace.Nested(python_config_update)
        }))
        def put(self, process_name):
            """Update configuration files for a process"""
            return self.pm2_service.update_process_config(process_name, namespace.payload)

    @namespace.route('/<string:process_name>/restart')
    class ProcessRestart(Resource):
        def __init__(self, api=None, *args, **kwargs):
            super().__init__(api)
            self.pm2_service = kwargs.get('pm2_service')

        @namespace.doc(
            responses={
                200: 'Process restarted',
                404: ('Process not found', error_model),
                500: ('Internal server error', error_model)
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

    @namespace.route('/<string:process_name>/stop')
    class ProcessStop(Resource):
        def __init__(self, api=None, *args, **kwargs):
            super().__init__(api)
            self.pm2_service = kwargs.get('pm2_service')

        @namespace.doc(
            responses={
                200: 'Process stopped',
                404: ('Process not found', error_model),
                500: ('Internal server error', error_model)
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

    @namespace.route('/<string:process_name>/start')
    class ProcessStart(Resource):
        def __init__(self, api=None, *args, **kwargs):
            super().__init__(api)
            self.pm2_service = kwargs.get('pm2_service')

        @namespace.doc(
            responses={
                200: 'Process started',
                404: ('Process not found', error_model),
                500: ('Internal server error', error_model)
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

    return {
        'ProcessList': ProcessList,
        'Process': Process,
        'ProcessConfig': ProcessConfig,
        'ProcessRestart': ProcessRestart,
        'ProcessStop': ProcessStop,
        'ProcessStart': ProcessStart
    }