# /api/routes/logs.py

from datetime import datetime
from flask import request
from flask_restx import Resource, fields
from core.exceptions import ProcessNotFoundError
from typing import Dict, Optional

def create_log_routes(namespace, services=None):
    """Create enhanced log management routes"""
    
    # Create models for request parameters
    log_params = namespace.model('LogParameters', {
        'logType': fields.String(description='Log type (error/out)', enum=['error', 'out'], default='out'),
        'lines': fields.Integer(description='Number of lines to return', default=100, min=1, max=10000)
    })

    # Create model for log response
    log_response = namespace.model('LogResponse', {
        'logs': fields.List(fields.String, description='Log entries'),
        'files': fields.Raw(description='Log file information'),
        'metadata': fields.Raw(description='Log metadata')
    })
    
    @namespace.route('/<string:process_name>')
    class ProcessLogs(Resource):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.log_manager = services['log_manager']
            self.logger = services['logger']
            self.pm2_service = services['pm2_service']

        @namespace.doc(
            params={
                'logType': {'description': 'Log type (error/out)', 'enum': ['error', 'out'], 'default': 'out'},
                'lines': {'description': 'Number of lines to return', 'type': 'integer', 'default': 100}
            },
            responses={
                200: 'Success',
                404: 'Process not found',
                400: 'Invalid parameters',
                500: 'Internal server error'
            }
        )
        @namespace.expect(log_params)
        @namespace.marshal_with(log_response)
        def get(self, process_name: str):
            """Get process logs with type filtering"""
            try:
                # Parse and validate parameters
                params = self._parse_log_parameters(request.args)
                
                # Verify process exists
                process = self.pm2_service.get_process(process_name)
                
                # Get log paths from PM2 environment
                log_paths = self._get_log_paths(process['pm2_env'])
                
                # Get logs based on type
                log_type = params['logType']
                num_lines = params['lines']
                
                logs_data = self.log_manager.get_process_logs_by_type(
                    process_name=process_name,
                    log_type=log_type,
                    num_lines=num_lines,
                    log_paths=log_paths
                )
                
                # Add metadata
                logs_data['metadata'] = {
                    'timestamp': datetime.now().isoformat(),
                    'process_name': process_name,
                    'log_type': log_type,
                    'lines_requested': num_lines,
                    'lines_returned': len(logs_data['logs'])
                }
                
                return logs_data
                
            except ProcessNotFoundError as e:
                namespace.abort(404, str(e))
            except ValueError as e:
                namespace.abort(400, str(e))
            except Exception as e:
                self.logger.error(f"Error getting logs for {process_name}: {str(e)}")
                namespace.abort(500, f"Internal server error: {str(e)}")

        def _parse_log_parameters(self, args) -> Dict:
            """Parse and validate log request parameters"""
            try:
                # Handle both flat and structured parameters
                if 'lines[logType]' in args:
                    # Structured parameters
                    log_type = args.get('lines[logType]', 'out')
                    num_lines = int(args.get('lines[lines]', 100))
                else:
                    # Flat parameters
                    log_type = args.get('logType', 'out')
                    num_lines = int(args.get('lines', 100))
                
                # Validate log type
                if log_type not in ['error', 'out']:
                    raise ValueError(f"Invalid log type: {log_type}")
                
                # Validate number of lines
                if not 1 <= num_lines <= 10000:
                    raise ValueError("Number of lines must be between 1 and 10000")
                
                return {
                    'logType': log_type,
                    'lines': num_lines
                }
                
            except ValueError as e:
                raise ValueError(f"Invalid parameters: {str(e)}")

        def _get_log_paths(self, pm2_env: Dict) -> Dict:
            """Extract log paths from PM2 environment"""
            return {
                'out': pm2_env.get('pm_out_log_path'),
                'error': pm2_env.get('pm_err_log_path')
            }

        @namespace.doc(
            responses={
                200: 'Success',
                404: 'Process not found',
                500: 'Internal server error'
            }
        )
        def delete(self, process_name: str):
            """Clear process logs"""
            try:
                result = self.log_manager.clear_process_logs(process_name)
                return {
                    'message': f"Logs cleared for process {process_name}",
                    'files': result['files']
                }
                
            except ProcessNotFoundError as e:
                namespace.abort(404, str(e))
            except Exception as e:
                self.logger.error(f"Error clearing logs for {process_name}: {str(e)}")
                namespace.abort(500, f"Internal server error: {str(e)}")

    return None