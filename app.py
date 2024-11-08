from flask import Flask, redirect
from flask_restx import Api, Resource, fields, Namespace
from flask_cors import CORS
import subprocess
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime
from dotenv import load_dotenv
from typing import Dict, List, Optional, Union
import time

# Load environment variables
load_dotenv()

# Configuration
class Config:
    PORT = int(os.getenv('PORT', 5000))
    HOST = os.getenv('HOST', '0.0.0.0')
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT = os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    LOG_FILE = os.getenv('LOG_FILE', 'logs/pm2_controller.log')
    LOG_MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', 10485760))  # 10MB
    LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', 5))
    PM2_BIN = os.getenv('PM2_BIN', 'pm2')
    MAX_LOG_LINES = int(os.getenv('MAX_LOG_LINES', 1000))
    COMMAND_TIMEOUT = int(os.getenv('COMMAND_TIMEOUT', 30))  # seconds
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    RETRY_DELAY = int(os.getenv('RETRY_DELAY', 1))  # seconds

# Setup logging
os.makedirs('logs', exist_ok=True)
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, Config.LOG_LEVEL))

file_handler = RotatingFileHandler(
    Config.LOG_FILE,
    maxBytes=Config.LOG_MAX_BYTES,
    backupCount=Config.LOG_BACKUP_COUNT
)
file_handler.setFormatter(logging.Formatter(Config.LOG_FORMAT))
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(Config.LOG_FORMAT))
logger.addHandler(console_handler)

# Custom Exceptions
class PM2Error(Exception):
    """Base exception for PM2 related errors"""
    pass

class ProcessNotFoundError(PM2Error):
    """Raised when a PM2 process is not found"""
    pass

class ProcessAlreadyExistsError(PM2Error):
    """Raised when trying to create a process that already exists"""
    pass

class PM2CommandError(PM2Error):
    """Raised when a PM2 command fails"""
    pass

class PM2TimeoutError(PM2Error):
    """Raised when a PM2 command times out"""
    pass

# Initialize Flask app
app = Flask(__name__)
api = Api(app, 
    version='1.0', 
    title='PM2 Controller API',
    description='REST API for controlling PM2 processes',
    doc='/',
    prefix='/api'
)
CORS(app)
# Define namespaces
health_ns = api.namespace('health', description='Health checks')
processes_ns = api.namespace('processes', description='PM2 process operations')
logs_ns = api.namespace('logs', description='Process logs operations')

# Model definitions
monit_model = api.model('Monitoring', {
    'memory': fields.Integer(description='Memory usage in bytes'),
    'cpu': fields.Float(description='CPU usage percentage')
})

env_model = api.model('Environment', {
    'NODE_APP_INSTANCE': fields.Integer(description='Node app instance'),
    'PM2_HOME': fields.String(description='PM2 home directory'),
    'PYTHONUNBUFFERED': fields.String(description='Python unbuffered mode'),
    'unique_id': fields.String(description='Unique process ID'),
    'status': fields.String(description='Process status'),
    'pm_uptime': fields.Integer(description='Process uptime'),
    'restart_time': fields.Integer(description='Number of restarts'),
    'exit_code': fields.Integer(description='Process exit code')
})

pm2_env_model = api.model('PM2Environment', {
    'filter_env': fields.List(fields.String, description='Filtered environment variables'),
    'merge_logs': fields.Boolean(description='Merge logs flag'),
    'prev_restart_delay': fields.Integer(description='Previous restart delay'),
    'namespace': fields.String(description='Process namespace'),
    'kill_retry_time': fields.Integer(description='Kill retry timeout'),
    'windowsHide': fields.Boolean(description='Windows hide flag'),
    'username': fields.String(description='Process username'),
    'treekill': fields.Boolean(description='Tree kill flag'),
    'automation': fields.Boolean(description='Automation flag'),
    'pmx': fields.Boolean(description='PMX flag'),
    'instance_var': fields.String(description='Instance variable'),
    'exec_mode': fields.String(description='Execution mode'),
    'watch': fields.Boolean(description='Watch mode'),
    'autorestart': fields.Boolean(description='Auto restart flag'),
    'autostart': fields.Boolean(description='Auto start flag'),
    'vizion': fields.Boolean(description='Vizion flag'),
    'instances': fields.Integer(description='Number of instances'),
    'args': fields.List(fields.String, description='Process arguments'),
    'pm_exec_path': fields.String(description='Executable path'),
    'pm_cwd': fields.String(description='Working directory'),
    'exec_interpreter': fields.String(description='Interpreter'),
    'pm_out_log_path': fields.String(description='Output log path'),
    'pm_err_log_path': fields.String(description='Error log path'),
    'pm_pid_path': fields.String(description='PID file path'),
    'env': fields.Nested(env_model)
})

process_model = api.model('Process', {
    'pid': fields.Integer(description='Process ID'),
    'name': fields.String(description='Process name'),
    'pm2_env': fields.Nested(pm2_env_model),
    'pm_id': fields.Integer(description='PM2 ID'),
    'monit': fields.Nested(monit_model)
})

new_process_model = api.model('NewProcess', {
    'name': fields.String(required=True, description='Process name'),
    'script': fields.String(required=True, description='Script path'),
    'interpreter': fields.String(description='Python interpreter path'),
    'cwd': fields.String(description='Working directory'),
    'args': fields.List(fields.String, description='Script arguments'),
    'autorestart': fields.Boolean(description='Auto restart flag'),
    'watch': fields.Boolean(description='Watch mode flag'),
    'instances': fields.Integer(description='Number of instances')
})

error_model = api.model('Error', {
    'error': fields.String(description='Error message'),
    'error_type': fields.String(description='Error type'),
    'timestamp': fields.DateTime(description='Error timestamp'),
    'details': fields.Raw(description='Additional error details')
})

def parse_pm2_error(error_message: str) -> Exception:
    """Parse PM2 error messages and return appropriate exception"""
    error_lower = error_message.lower()
    if "process not found" in error_lower:
        return ProcessNotFoundError(error_message)
    elif "already exists" in error_lower:
        return ProcessAlreadyExistsError(error_message)
    else:
        return PM2CommandError(error_message)

def execute_pm2_command(command: str, retry: bool = True) -> Union[str, dict]:
    """
    Execute a PM2 command with enhanced error handling and retry logic
    
    Args:
        command: PM2 command to execute
        retry: Whether to retry on failure
        
    Returns:
        Command output as string or parsed JSON
        
    Raises:
        ProcessNotFoundError: When process is not found
        ProcessAlreadyExistsError: When process already exists
        PM2CommandError: For other PM2 related errors
        PM2TimeoutError: When command times out
    """
    retries = Config.MAX_RETRIES if retry else 1
    last_error = None
    
    for attempt in range(retries):
        try:
            result = subprocess.run(
                f"{Config.PM2_BIN} {command}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=Config.COMMAND_TIMEOUT
            )
            
            if result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode, 
                    command, 
                    result.stdout, 
                    result.stderr
                )
            
            if 'jlist' in command:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse PM2 JSON output: {str(e)}")
                    raise PM2CommandError(f"Invalid JSON output from PM2: {str(e)}")
            return result.stdout
            
        except subprocess.TimeoutExpired as e:
            last_error = PM2TimeoutError(f"Command timed out after {Config.COMMAND_TIMEOUT} seconds")
            logger.error(f"PM2 command timeout (attempt {attempt + 1}/{retries}): {str(e)}")
            
        except subprocess.CalledProcessError as e:
            last_error = parse_pm2_error(e.stderr.strip())
            logger.error(f"PM2 command failed (attempt {attempt + 1}/{retries}): {e.stderr}")
            
        except Exception as e:
            last_error = PM2CommandError(f"Failed to execute PM2 command: {str(e)}")
            logger.error(f"Unexpected error (attempt {attempt + 1}/{retries}): {str(e)}")
        
        if attempt < retries - 1:
            time.sleep(Config.RETRY_DELAY)
    
    raise last_error

@app.route('/')
def index():
    """Redirect root to Swagger UI"""
    return redirect('/api/')

@health_ns.route('/')
class HealthCheck(Resource):
    @api.doc(
        responses={
            200: 'Service is healthy',
            500: ('Service is unhealthy', error_model)
        }
    )
    def get(self):
        """Check service health status"""
        try:
            # Check PM2 daemon status
            execute_pm2_command('ping', retry=False)
            
            return {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "version": "1.0"
            }
        except Exception as e:
            return {
                'error': 'Service is unhealthy',
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': str(e)
            }, 500

@processes_ns.route('/')
class ProcessList(Resource):
    @api.doc(
        responses={
            200: ('Success', [process_model]),
            500: ('Internal server error', error_model)
        }
    )
    @api.marshal_list_with(process_model)
    def get(self):
        """Get list of all PM2 processes"""
        try:
            processes = execute_pm2_command("jlist")
            return processes
        except Exception as e:
            return {
                'error': str(e),
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': None
            }, 500

    @api.doc(
        responses={
            201: ('Process created', process_model),
            400: ('Invalid input', error_model),
            409: ('Process already exists', error_model),
            500: ('Internal server error', error_model)
        }
    )
    @api.expect(new_process_model)
    def post(self):
        """Create a new PM2 process"""
        try:
            data = api.payload
            cmd_parts = [
                Config.PM2_BIN,
                'start',
                data['script'],
                '--name', data['name']
            ]
            
            if 'interpreter' in data:
                cmd_parts.extend(['--interpreter', data['interpreter']])
            if 'cwd' in data:
                cmd_parts.extend(['--cwd', data['cwd']])
            if 'instances' in data:
                cmd_parts.extend(['-i', str(data['instances'])])
            if 'watch' in data and data['watch']:
                cmd_parts.append('--watch')
            if 'args' in data:
                cmd_parts.extend(['--', *data['args']])
            
            subprocess.run(cmd_parts, check=True, capture_output=True, text=True)
            
            # Get process details after creation
            processes = execute_pm2_command("jlist")
            process = next((p for p in processes if p['name'] == data['name']), None)
            
            return process, 201
            
        except ProcessAlreadyExistsError as e:
            return {
                'error': str(e),
                'error_type': 'ProcessAlreadyExistsError',
                'timestamp': datetime.now().isoformat(),
                'details': {'process_name': data['name']}
            }, 409
        except subprocess.CalledProcessError as e:
            return {
                'error': f"Failed to create process: {e.stderr}",
                'error_type': 'ProcessCreationError',
                'timestamp': datetime.now().isoformat(),
                'details': {'command': ' '.join(cmd_parts)}
            }, 500
        except Exception as e:
            return {
                'error': str(e),
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': None
            }, 500

@processes_ns.route('/<string:process_name>')
@api.doc(params={'process_name': 'Name of the PM2 process'})
class Process(Resource):
    @api.doc(
        responses={
            200: ('Success', process_model),
            404: ('Process not found', error_model),
            500: ('Internal server error', error_model)
        }
    )
    @api.marshal_with(process_model)
    def get(self, process_name):
        """Get details of a specific process"""
        try:
            processes = execute_pm2_command("jlist")
            process = next((p for p in processes if p['name'] == process_name), None)
            
            if not process:
                raise ProcessNotFoundError(f"Process {process_name} not found")
            
            return process
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

    @api.doc(
        responses={
            200: 'Process deleted',
            404: ('Process not found', error_model),
            500: ('Internal server error', error_model)
        }
    )
    def delete(self, process_name):
        """Delete a specific process"""
        try:
            execute_pm2_command(f"delete {process_name}")
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

@processes_ns.route('/<string:process_name>/restart')
class ProcessRestart(Resource):
    @api.doc(
        responses={
            200: 'Process restarted',
            404: ('Process not found', error_model),
            500: ('Internal server error', error_model)
        }
    )
    def post(self, process_name):
        """Restart a specific process by name, using pm_id"""
        try:
            processes = execute_pm2_command("jlist")
            process = next((p for p in processes if p['name'] == process_name), None)
            if not process:
                raise ProcessNotFoundError(f"Process {process_name} not found")
            
            pm_id = process['pm_id']
            execute_pm2_command(f"restart {pm_id}")
            return {"message": f"Process {process_name} (ID: {pm_id}) restarted successfully"}
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

@processes_ns.route('/<string:process_name>/stop')
class ProcessStop(Resource):
    @api.doc(
        responses={
            200: 'Process stopped',
            404: ('Process not found', error_model),
            500: ('Internal server error', error_model)
        }
    )
    def post(self, process_name):
        """Stop a specific process by name, using pm_id"""
        try:
            processes = execute_pm2_command("jlist")
            process = next((p for p in processes if p['name'] == process_name), None)
            if not process:
                raise ProcessNotFoundError(f"Process {process_name} not found")
            
            pm_id = process['pm_id']
            execute_pm2_command(f"stop {pm_id}")
            return {"message": f"Process {process_name} (ID: {pm_id}) stopped successfully"}
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
            
@processes_ns.route('/<string:process_name>/start')
class ProcessStart(Resource):
    @api.doc(
        responses={
            200: 'Process started',
            404: ('Process not found', error_model),
            500: ('Internal server error', error_model)
        }
    )
    def post(self, process_name):
        """Start a specific process by name, using pm_id"""
        try:
            processes = execute_pm2_command("jlist")
            process = next((p for p in processes if p['name'] == process_name), None)
            if not process:
                raise ProcessNotFoundError(f"Process {process_name} not found")
            
            pm_id = process['pm_id']
            execute_pm2_command(f"start {pm_id}")
            return {"message": f"Process {process_name} (ID: {pm_id}) started successfully"}
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


@logs_ns.route('/<string:process_name>')
class ProcessLogs(Resource):
    @api.doc(
        responses={
            200: 'Success',
            404: ('Process not found', error_model),
            500: ('Internal server error', error_model)
        },
        params={
            'lines': {'type': 'integer', 'default': 100, 'description': 'Number of log lines to return'},
            'format': {'type': 'string', 'enum': ['raw', 'json'], 'default': 'raw', 'description': 'Log format'}
        }
    )
    def get(self, process_name):
        """Get logs for a specific process"""
        try:
            from flask import request
            lines = min(int(request.args.get('lines', 100)), Config.MAX_LOG_LINES)
            format_type = request.args.get('format', 'raw')

            # First verify process exists
            processes = execute_pm2_command("jlist")
            process = next((p for p in processes if p['name'] == process_name), None)
            
            if not process:
                raise ProcessNotFoundError(f"Process {process_name} not found")

            logs = execute_pm2_command(f"logs {process_name} --lines {lines} --nostream")
            
            if format_type == 'json':
                # Parse logs into structured format
                log_entries = []
                for line in logs.splitlines():
                    if line.strip():
                        try:
                            timestamp = None
                            message = line
                            
                            # Try to extract timestamp if present
                            if ' -- ' in line:
                                parts = line.split(' -- ', 1)
                                try:
                                    timestamp = datetime.strptime(
                                        parts[0].strip(), 
                                        '%Y-%m-%d %H:%M:%S'
                                    ).isoformat()
                                    message = parts[1]
                                except ValueError:
                                    pass
                            
                            log_entries.append({
                                'timestamp': timestamp,
                                'message': message.strip(),
                                'type': 'error' if 'error' in line.lower() else 'out'
                            })
                        except Exception as e:
                            logger.warning(f"Failed to parse log line: {line}")
                            log_entries.append({
                                'timestamp': None,
                                'message': line.strip(),
                                'type': 'unknown'
                            })
                
                return {
                    'process_name': process_name,
                    'total_lines': len(log_entries),
                    'logs': log_entries
                }
            else:
                return {
                    'process_name': process_name,
                    'logs': logs
                }
                
        except ProcessNotFoundError as e:
            return {
                'error': str(e),
                'error_type': 'ProcessNotFoundError',
                'timestamp': datetime.now().isoformat(),
                'details': {'process_name': process_name}
            }, 404
        except ValueError as e:
            return {
                'error': 'Invalid parameter value',
                'error_type': 'ValueError',
                'timestamp': datetime.now().isoformat(),
                'details': str(e)
            }, 400
        except Exception as e:
            return {
                'error': str(e),
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': None
            }, 500

@processes_ns.route('/<string:process_name>/reload')
class ProcessReload(Resource):
    @api.doc(
        responses={
            200: 'Process reloaded',
            404: ('Process not found', error_model),
            500: ('Internal server error', error_model)
        }
    )
    def post(self, process_name):
        """Reload a specific process (zero-downtime restart)"""
        try:
            execute_pm2_command(f"reload {process_name}")
            return {"message": f"Process {process_name} reloaded successfully"}
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

if __name__ == '__main__':
    try:
        logger.info("Starting PM2 Controller API")
        app.run(
            host=Config.HOST,
            port=Config.PORT,
            debug=Config.DEBUG
        )
    except Exception as e:
        logger.error(f"Service startup failed: {str(e)}")
        raise
