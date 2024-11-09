from datetime import datetime
from flask import request
from flask_restx import Resource
from core.exceptions import ProcessNotFoundError

def create_log_routes(namespace):
    """Create log management routes"""
    
    @namespace.route('/<string:process_name>')
    class ProcessLogs(Resource):
        def __init__(self, api=None, log_manager=None, logger=None, **kwargs):
            super().__init__(api)
            self.log_manager = log_manager
            self.logger = logger
            
            if not self.log_manager or not self.logger:
                raise ValueError("Required services not provided: log_manager and logger are required")

        @namespace.doc(
            params={
                'format': 'Log format (raw)',
                'lines': 'Number of lines to return (default: 100)'
            },
            responses={
                200: 'Success',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        def get(self, process_name):
            """Get process logs"""
            try:
                num_lines = request.args.get('lines', type=int, default=100)
                return self.log_manager.get_process_logs(process_name, num_lines)
                
            except ProcessNotFoundError as e:
                return {
                    'error': str(e),
                    'error_type': 'ProcessNotFoundError',
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 404
                
            except Exception as e:
                self.logger.error(f"Error getting logs for {process_name}: {str(e)}")
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 500

        @namespace.doc(
            responses={
                200: 'Success',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        def delete(self, process_name):
            """Clear process logs"""
            try:
                return self.log_manager.clear_process_logs(process_name)
                
            except ProcessNotFoundError as e:
                return {
                    'error': str(e),
                    'error_type': 'ProcessNotFoundError',
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 404
                
            except Exception as e:
                self.logger.error(f"Error clearing logs for {process_name}: {str(e)}")
                return {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'timestamp': datetime.now().isoformat(),
                    'details': {'process_name': process_name}
                }, 500

    return {'ProcessLogs': ProcessLogs}