# /api/routes/processes.py

from datetime import datetime
from pathlib import Path
from flask_restx import Resource
from core.exceptions import ProcessNotFoundError, ProcessAlreadyExistsError, PM2CommandError

def create_process_routes(namespace, services=None):
    """Create process management routes"""
    
@namespace.route('/')
class ProcessList(Resource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pm2_service = services['pm2_service']
        self.process_manager = services['process_manager']
        self.logger = services['logger']
        self.config = services['config']

    @namespace.doc(
        responses={
            200: 'Success',
            500: 'Internal server error'
        }
    )
    def get(self):
        """Get list of all PM2 processes"""
        try:
            # Fetch processes from PM2 service
            processes = self.pm2_service.list_processes()

            # Enhance process details with configuration file paths
            for process in processes:
                try:
                    # Paths for PM2 and Python configuration files
                    pm2_config = Path(f"{self.config.PM2_CONFIG_DIR}/{process['name']}.config.js")
                    python_config = Path(f"{self.config.PM2_CONFIG_DIR}/{process['name']}.ini")

                    # Add config file paths if they exist
                    process['config_files'] = {
                        'pm2_config': str(pm2_config) if pm2_config.exists() else None,
                        'python_config': str(python_config) if python_config.exists() else None
                    }
                except Exception as e:
                    self.logger.warning(f"Error getting config paths for process {process.get('name', 'unknown')}: {str(e)}")

            # Return the list of processes
            return {'success': True, 'processes': processes}, 200

        except Exception as e:
            # Log the error
            self.logger.error(f"Error getting process list: {str(e)}", exc_info=True)

            # Return an error response
            return {
                'error': 'Failed to retrieve PM2 processes',
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
            # Create the process using the payload from the request
            result = self.process_manager.create_process(namespace.payload)

            # Return success response
            return {'success': True, 'details': result}, 201

        except ProcessAlreadyExistsError as e:
            # Handle case where the process already exists
            self.logger.warning(f"Process already exists: {namespace.payload.get('name')}")
            return {
                'error': str(e),
                'error_type': 'ProcessAlreadyExistsError',
                'timestamp': datetime.now().isoformat(),
                'details': {'process_name': namespace.payload.get('name')}
            }, 409

        except KeyError as e:
            # Handle missing required fields in the payload
            self.logger.error(f"Invalid input data: Missing key {str(e)}", exc_info=True)
            return {
                'error': f"Missing required key: {str(e)}",
                'error_type': 'KeyError',
                'timestamp': datetime.now().isoformat(),
                'details': None
            }, 400

        except Exception as e:
            # Log unexpected errors
            self.logger.error(f"Error creating process: {str(e)}", exc_info=True)

            # Return a generic error response
            return {
                'error': 'An unexpected error occurred while creating the process',
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': None
            }, 500
            
    @namespace.route('/<string:process_name>')
    class Process(Resource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pm2_service = services['pm2_service']
            self.logger = services['logger']

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
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pm2_service = services['pm2_service']
            self.logger = services['logger']

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
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pm2_service = services['pm2_service']
            self.logger = services['logger']

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
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pm2_service = services['pm2_service']
            self.logger = services['logger']

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

    @namespace.route('/<string:process_name>/update')
    class ProcessUpdate(Resource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.process_manager = services['process_manager']
            self.logger = services['logger']

        @namespace.doc(
            responses={
                200: "Process updated successfully",
                404: "Process not found",
                500: "Update failed",
            }
        )
        def post(self, process_name):
            """Update a process using PM2 deploy command."""
            try:
                result = self.process_manager.update_process(process_name)
                return result, 200
            except ProcessNotFoundError as e:
                return {
                    "error": str(e),
                    "error_type": "ProcessNotFoundError",
                    "timestamp": datetime.now().isoformat(),
                    "details": {"process_name": process_name}
                }, 404
            except PM2CommandError as e:
                return {
                    "error": str(e),
                    "error_type": "PM2CommandError",
                    "timestamp": datetime.now().isoformat(),
                    "details": {
                        "process_name": process_name,
                        "command_output": str(e)
                    }
                }, 500
            except Exception as e:
                return {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "timestamp": datetime.now().isoformat(),
                    "details": {"process_name": process_name}
                }, 500

   
    @namespace.route('/<string:process_name>/config')
    class ProcessConfigUpdate(Resource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.process_manager = services['process_manager']
            self.logger = services['logger']
        
        @namespace.doc(
            responses={
                200: 'Current configuration',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        def get(self, process_name):
            """Get current process configuration"""
            try:
                config = self.process_manager.get_process_config(process_name)
                return config
                
            except ProcessNotFoundError as e:
                return {
                    'error': str(e),
                    'error_type': 'ProcessNotFoundError',
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 404
                
            except Exception as e:
                self.logger.error(f"Error getting config for {process_name}: {str(e)}")
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 500

        @namespace.doc(
            responses={
                200: 'Configuration updated successfully',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        @namespace.expect(namespace.models['update_config'])
        def put(self, process_name):
            """Update process configuration"""
            try:
                result = self.process_manager.update_config(process_name, namespace.payload)
                return result
                
            except ProcessNotFoundError as e:
                return {
                    'error': str(e),
                    'error_type': 'ProcessNotFoundError',
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 404
                
            except Exception as e:
                self.logger.error(f"Error updating config for {process_name}: {str(e)}")
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 500


    return None