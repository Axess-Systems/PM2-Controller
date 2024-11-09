from datetime import datetime
from flask import request
from flask_restx import Resource
from core.exceptions import ProcessNotFoundError

class ProcessLogs(Resource):
    def __init__(self, api, log_manager):
        super().__init__()
        self.api = api
        self.log_manager = log_manager
        
        # Setup route documentation
        self.get.__doc__ = "Get process logs"
        self.get = self.api.doc(
            params={
                'format': 'Log format (raw)',
                'lines': 'Number of lines to return (default: 100)'
            },
            responses={
                200: 'Success',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )(self.get)

        self.delete.__doc__ = "Clear process logs"
        self.delete = self.api.doc(
            responses={
                200: 'Logs cleared successfully',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )(self.delete)

    def get(self, process_name):
        """Get process logs"""
        try:
            # Get format and lines parameters
            num_lines = request.args.get('lines', type=int, default=100)
            
            logs = self.log_manager.get_process_logs(
                process_name=process_name,
                num_lines=num_lines
            )
            
            return logs
            
        except ProcessNotFoundError as e:
            return {
                'error': str(e),
                'error_type': 'ProcessNotFoundError',
                'timestamp': datetime.now().isoformat(),
                'details': {
                    'process_name': process_name,
                }
            }, 404
        except Exception as e:
            return {
                'error': str(e),
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': {
                    'process_name': process_name
                }
            }, 500

    def delete(self, process_name):
        """Clear process logs"""
        try:
            result = self.log_manager.clear_process_logs(process_name)
            return result
            
        except ProcessNotFoundError as e:
            return {
                'error': str(e),
                'error_type': 'ProcessNotFoundError',
                'timestamp': datetime.now().isoformat(),
                'details': {
                    'process_name': process_name
                }
            }, 404
        except Exception as e:
            return {
                'error': str(e),
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': {
                    'process_name': process_name
                }
            }, 500