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
from pathlib import Path


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

# Base environment variables that every process has
base_env_model = api.model('BaseEnvironment', {
    'NODE_APP_INSTANCE': fields.Integer(description='Node app instance'),
    'PM2_HOME': fields.String(description='PM2 home directory'),
    'PYTHONUNBUFFERED': fields.String(description='Python unbuffered mode'),
    'unique_id': fields.String(description='Unique process ID'),
    'USER': fields.String(description='Username'),
    'HOME': fields.String(description='Home directory'),
    'SHELL': fields.String(description='Shell'),
    'PATH': fields.String(description='System PATH'),
    'PWD': fields.String(description='Working directory'),
    'LANG': fields.String(description='System language'),
    'XDG_SESSION_TYPE': fields.String(description='Session type'),
    'TERM': fields.String(description='Terminal type')
})

# Model for process monitoring stats
monit_model = api.model('Monitoring', {
    'memory': fields.Integer(description='Memory usage in bytes'),
    'cpu': fields.Float(description='CPU usage percentage')
})

# Extended PM2 environment configuration
pm2_env_model = api.model('PM2Environment', {
    # Process Configuration
    'name': fields.String(description='Process name'),
    'namespace': fields.String(description='Process namespace', default='default'),
    'version': fields.String(description='Application version', default='N/A'),
    'instances': fields.Integer(description='Number of instances', default=1),
    
    # Execution Settings
    'exec_interpreter': fields.String(description='Script interpreter'),
    'pm_exec_path': fields.String(description='Script path'),
    'pm_cwd': fields.String(description='Working directory'),
    'args': fields.List(fields.String, description='Script arguments'),
    'node_args': fields.List(fields.String, description='Node.js arguments'),
    
    # Runtime Configuration
    'watch': fields.Boolean(description='Watch mode', default=False),
    'autorestart': fields.Boolean(description='Auto restart flag', default=True),
    'autostart': fields.Boolean(description='Auto start flag', default=True),
    'vizion': fields.Boolean(description='Version control tracking', default=True),
    'automation': fields.Boolean(description='Automation enabled', default=True),
    'pmx': fields.Boolean(description='PMX monitoring', default=True),
    'treekill': fields.Boolean(description='Kill process tree', default=True),
    'windowsHide': fields.Boolean(description='Hide window on Windows', default=True),
    
    # Paths and Logs
    'pm_out_log_path': fields.String(description='Output log path'),
    'pm_err_log_path': fields.String(description='Error log path'),
    'pm_pid_path': fields.String(description='PID file path'),
    'merge_logs': fields.Boolean(description='Merge logs flag', default=True),
    
    # Process State
    'status': fields.String(description='Process status', 
        enum=['online', 'stopping', 'stopped', 'launching', 'errored', 'one-launch-status']),
    'pm_uptime': fields.Integer(description='Process uptime'),
    'created_at': fields.Integer(description='Creation timestamp'),
    'pm_id': fields.Integer(description='PM2 process ID'),
    'restart_time': fields.Integer(description='Number of restarts', default=0),
    'unstable_restarts': fields.Integer(description='Number of unstable restarts', default=0),
    'exit_code': fields.Integer(description='Exit code'),
    
    # Control Settings
    'kill_retry_time': fields.Integer(description='Kill retry timeout', default=100),
    'prev_restart_delay': fields.Integer(description='Previous restart delay', default=0),
    'instance_var': fields.String(description='Instance variable', default='NODE_APP_INSTANCE'),
    
    # Environment
    'filter_env': fields.List(fields.String, description='Filtered environment variables'),
    'env': fields.Nested(base_env_model, description='Environment variables'),
    
    # Monitoring
    'axm_actions': fields.List(fields.Raw, description='PM2 module actions'),
    'axm_monitor': fields.Raw(description='Custom metrics'),
    'axm_options': fields.Raw(description='Module options'),
    'axm_dynamic': fields.Raw(description='Dynamic configuration')
})

# Main process model
process_model = api.model('Process', {
    'pid': fields.Integer(description='Process ID'),
    'name': fields.String(description='Process name'),
    'pm2_env': fields.Nested(pm2_env_model, description='PM2 environment configuration'),
    'pm_id': fields.Integer(description='PM2 ID'),
    'monit': fields.Nested(monit_model, description='Process monitoring statistics')
})

# Model for creating new processes
new_process_model = api.model('NewProcess', {
    'name': fields.String(required=True, description='Process name'),
    'script': fields.String(required=True, description='Script path'),
    'interpreter': fields.String(description='Script interpreter', default='python3'),
    'cwd': fields.String(description='Working directory'),
    'args': fields.List(fields.String, description='Script arguments'),
    'env': fields.Raw(description='Environment variables'),
    'instances': fields.Integer(description='Number of instances', default=1),
    'autorestart': fields.Boolean(description='Auto restart flag', default=True),
    'watch': fields.Boolean(description='Watch mode', default=False),
    'merge_logs': fields.Boolean(description='Merge logs', default=True),
    'cron_restart': fields.String(description='Cron pattern for automatic restart'),
    'max_memory_restart': fields.String(description='Max memory before restart'),
})

# Error response model
error_model = api.model('Error', {
    'error': fields.String(description='Error message'),
    'error_type': fields.String(description='Error type'),
    'timestamp': fields.DateTime(description='Error timestamp'),
    'details': fields.Raw(description='Additional error details')
})

new_process_model = api.model('NewProcess', {
    'name': fields.String(required=True, description='Process name'),
    'script': fields.String(required=True, description='Script path or relative path'),
    'repository': fields.Nested(api.model('Repository', {
        'url': fields.String(required=True, description='GitHub repository URL'),
        'project_dir': fields.String(required=True, description='Project directory name'),
        'branch': fields.String(required=True, description='Git branch name')
    })),
    'python': fields.Nested(api.model('PythonConfig', {
        'requirements_file': fields.String(description='Path to requirements.txt', default='requirements.txt'),
        'run_script': fields.String(description='Python script to run', default='app.py'),
        'arguments': fields.String(description='Additional script arguments', default=''),
        'variables': fields.Raw(description='Environment variables for Python'),
        'smtp': fields.Nested(api.model('SMTPConfig', {
            'enabled': fields.Boolean(description='Enable SMTP', default=False)
        })),
        'citrix_customer_api': fields.Nested(api.model('CitrixCustomerAPI', {
            'enabled': fields.Boolean(description='Enable Citrix Customer API', default=False),
            'customers': fields.List(fields.String, description='List of customers')
        }))
    })),
    'pm2': fields.Nested(api.model('PM2Config', {
        'instances': fields.Integer(description='Number of instances', default=1),
        'exec_mode': fields.String(description='Execution mode', default='fork'),
        'cron_restart': fields.String(description='Cron pattern for restart'),
        'watch': fields.Boolean(description='Enable watch mode', default=False),
        'autorestart': fields.Boolean(description='Enable auto-restart', default=True)
    }))
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


def create_pm2_config(process_name: str, config: dict) -> str:
    """Create PM2 config file in CommonJS format"""
    pm2_config_dir = Path('/home/pm2/pm2-configs')
    pm2_config_dir.mkdir(parents=True, exist_ok=True)
    
    config_path = pm2_config_dir / f"{process_name}.config.js"
    
    # Format the PM2 config
    pm2_config = {
        "name": process_name,
        "script": f"~/Python-Reporting-Wrapper/{config['python']['run_script']}",
        "args": config.get('python', {}).get('arguments', ''),
        "instances": config.get('pm2', {}).get('instances', 1),
        "exec_mode": config.get('pm2', {}).get('exec_mode', 'fork'),
        "cron_restart": config.get('pm2', {}).get('cron_restart'),
        "watch": config.get('pm2', {}).get('watch', False),
        "autorestart": config.get('pm2', {}).get('autorestart', True)
    }
    
    # Write config in CommonJS format
    with open(config_path, 'w') as f:
        f.write("module.exports = {\n")
        f.write("  apps: [\n")
        f.write("    " + json.dumps(pm2_config, indent=2).replace('"', "'") + "\n")
        f.write("  ]\n")
        f.write("};\n")
    
    return str(config_path)

def create_python_config(process_name: str, config: dict) -> str:
    """Create Python INI config file"""
    python_config_dir = Path('/home/pm2/Python-Reporting-Wrapper')
    python_config_dir.mkdir(parents=True, exist_ok=True)
    
    config_path = python_config_dir / f"{process_name}.ini"
    
    with open(config_path, 'w') as f:
        # Repository section
        f.write("[repository]\n")
        f.write(f"url = {config['repository']['url']}\n")
        f.write(f"project_dir = {config['repository']['project_dir']}\n")
        f.write(f"branch = {config['repository']['branch']}\n\n")
        
        # Dependencies section
        f.write("[dependencies]\n")
        f.write(f"requirements_file = {config['python']['requirements_file']}\n")
        f.write(f"run_script = {config['python']['run_script']}\n")
        f.write(f"arguments = {config['python']['arguments']}\n\n")
        
        # Variables section if present
        if 'variables' in config['python']:
            f.write("[variables]\n")
            for key, value in config['python']['variables'].items():
                f.write(f"{key} = {value}\n")
            f.write("\n")
        
        # SMTP section if enabled
        if config['python'].get('smtp', {}).get('enabled'):
            f.write("[smtp]\n")
            f.write("enabled = true\n\n")
        
        # Citrix Customer API section if enabled
        if config['python'].get('citrix_customer_api', {}).get('enabled'):
            f.write("[citrix_customer_api]\n")
            f.write("enabled = true\n")
            customers = config['python']['citrix_customer_api'].get('customers', [])
            if customers:
                f.write(f"customers = {', '.join(customers)}\n")
    
    return str(config_path)



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
            
            # Add config file paths to process details
            for process in processes:
                try:
                    # Get config file paths
                    pm2_config = Path(f"/home/pm2/pm2-configs/{process['name']}.config.js")
                    python_config = Path(f"/home/pm2/Python-Reporting-Wrapper/{process['name']}.ini")
                    
                    process['config_files'] = {
                        'pm2_config': str(pm2_config) if pm2_config.exists() else None,
                        'python_config': str(python_config) if python_config.exists() else None
                    }
                except Exception as e:
                    logger.warning(f"Error getting config paths for process {process['name']}: {str(e)}")
            
            return processes
            
        except Exception as e:
            logger.error(f"Error getting process list: {str(e)}")
            return {
                'error': str(e),
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': {
                    'command': 'pm2 jlist',
                    'error_details': str(e)
                }
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
            process_name = data['name']
            
            # Check if process already exists
            existing_processes = execute_pm2_command("jlist")
            if any(p['name'] == process_name for p in existing_processes):
                raise ProcessAlreadyExistsError(f"Process {process_name} already exists")
            
            # Create directories if they don't exist
            pm2_configs_dir = Path('/home/pm2/pm2-configs')
            python_wrapper_dir = Path('/home/pm2/Python-Reporting-Wrapper')
            pm2_configs_dir.mkdir(parents=True, exist_ok=True)
            python_wrapper_dir.mkdir(parents=True, exist_ok=True)
            
            # Create PM2 config file
            pm2_config_path = pm2_configs_dir / f"{process_name}.config.js"
            pm2_config = {
                "name": process_name,
                "script": "~/Python-Reporting-Wrapper/app.py",
                "args": f"{process_name}.ini",
                "instances": data.get('pm2', {}).get('instances', 1),
                "exec_mode": 'fork',
                "cron_restart": data.get('pm2', {}).get('cron_restart'),
                "watch": data.get('pm2', {}).get('watch', False),
                "autorestart": data.get('pm2', {}).get('autorestart', True)
            }
            
            # Write PM2 config
            with open(pm2_config_path, 'w') as f:
                f.write("module.exports = {\n")
                f.write("  apps: [\n")
                f.write("    " + json.dumps(pm2_config, indent=2).replace('"', "'") + "\n")
                f.write("  ]\n")
                f.write("};\n")
            
            # Create Python config file
            python_config_path = python_wrapper_dir / f"{process_name}.ini"
            with open(python_config_path, 'w') as f:
                # Repository section
                f.write("[repository]\n")
                f.write(f"url = {data['repository']['url']}\n")
                f.write(f"project_dir = {data['repository']['project_dir']}\n")
                f.write(f"branch = {data['repository']['branch']}\n\n")
                
                # Dependencies section
                f.write("[dependencies]\n")
                f.write(f"requirements_file = {data['python'].get('requirements_file', 'requirements.txt')}\n")
                f.write(f"run_script = {data['python'].get('run_script', 'app.py')}\n")
                f.write(f"arguments = {data['python'].get('arguments', '')}\n\n")
                
                # Optional sections
                if 'variables' in data['python']:
                    f.write("[variables]\n")
                    for key, value in data['python']['variables'].items():
                        f.write(f"{key} = {value}\n")
                    f.write("\n")
                
                if data['python'].get('smtp', {}).get('enabled'):
                    f.write("[smtp]\n")
                    f.write("enabled = true\n\n")
                
                if data['python'].get('citrix_customer_api', {}).get('enabled'):
                    f.write("[citrix_customer_api]\n")
                    f.write("enabled = true\n")
                    customers = data['python']['citrix_customer_api'].get('customers', [])
                    if customers:
                        f.write(f"customers = {', '.join(customers)}\n")
            
            # Start the process from pm2-configs directory
            original_dir = os.getcwd()
            try:
                os.chdir(pm2_configs_dir)
                start_cmd = [Config.PM2_BIN, 'start', f"{process_name}.config.js"]
                
                subprocess.run(
                    start_cmd,
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                return {
                    "message": f"Process {process_name} configuration created successfully",
                    "config_files": {
                        "pm2_config": str(pm2_config_path),
                        "python_config": str(python_config_path)
                    }
                }, 201
                
            finally:
                os.chdir(original_dir)
                
        except ProcessAlreadyExistsError as e:
            logger.error(f"Process already exists: {str(e)}")
            return {
                'error': str(e),
                'error_type': 'ProcessAlreadyExistsError',
                'timestamp': datetime.now().isoformat(),
                'details': {
                    'process_name': process_name
                }
            }, 409
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create process {process_name}: {e.stderr}")
            return {
                'error': f"Failed to create process: {e.stderr}",
                'error_type': 'ProcessCreationError',
                'timestamp': datetime.now().isoformat(),
                'details': {
                    'command': ' '.join(start_cmd),
                    'stdout': e.stdout,
                    'stderr': e.stderr,
                    'exit_code': e.returncode
                }
            }, 500
            
        except Exception as e:
            logger.error(f"Unexpected error creating process {process_name}: {str(e)}")
            return {
                'error': str(e),
                'error_type': type(e).__name__,
                'timestamp': datetime.now().isoformat(),
                'details': {
                    'process_name': process_name,
                    'config_paths': {
                        'pm2': str(pm2_config_path) if 'pm2_config_path' in locals() else None,
                        'python': str(python_config_path) if 'python_config_path' in locals() else None
                    }
                }
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
        }
    )
    def get(self, process_name):
        """Get process details for a specific process"""
        try:
            # Get all processes data
            processes = execute_pm2_command("jlist")
            
            # Find the specific process
            process = next((p for p in processes if p['name'] == process_name), None)
            
            if not process:
                raise ProcessNotFoundError(f"Process {process_name} not found")

            # Return the complete process data
            return jsonify(process)
                
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
