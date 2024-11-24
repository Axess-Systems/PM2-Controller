# /api/models/Process.py
from flask_restx import fields

def create_api_models(api):
    """Create and register API models for process management"""
    
    # Process monitoring stats model
    monit_model = api.model('Monitoring', {
        'memory': fields.Integer(description='Memory usage in bytes'),
        'cpu': fields.Float(description='CPU usage percentage')
    })

    # Main process model for viewing process status
    process_model = api.model('Process', {
        'pid': fields.Integer(description='Process ID'),
        'name': fields.String(description='Process name'),
        'pm_id': fields.Integer(description='PM2 ID'),
        'monit': fields.Nested(monit_model, description='Process monitoring statistics'),
        'status': fields.String(description='Process status'),
        'pm_uptime': fields.Integer(description='Process uptime'),
        'restart_time': fields.Integer(description='Number of restarts'),
        'unstable_restarts': fields.Integer(description='Number of unstable restarts'),
        'created_at': fields.Integer(description='Creation timestamp')
    })

    # Environment variables model
    env_config_model = api.model('EnvConfig', {
        'PORT': fields.String(description='Application port', default="5001"),
        'HOST': fields.String(description='Application host', default="0.0.0.0"),
        'DEBUG': fields.String(description='Debug mode', default="False"),
        'LOG_LEVEL': fields.String(description='Logging level', default="INFO"),
        'PM2_BIN': fields.String(description='PM2 binary path', default="pm2"),
        'MAX_LOG_LINES': fields.String(description='Maximum log lines', default="1000"),
        'COMMAND_TIMEOUT': fields.String(description='Command timeout in seconds', default="30"),
        'MAX_RETRIES': fields.String(description='Maximum retry attempts', default="3"),
        'RETRY_DELAY': fields.String(description='Retry delay in seconds', default="1")
    })

    # Model for creating new processes - keeping original structure
    new_process_model = api.model('NewProcess', {
        'name': fields.String(required=True, description='Process name'),
        'repository': fields.Nested(api.model('Repository', {
            'url': fields.String(required=True, description='GitHub repository URL'),
            'branch': fields.String(description='Git branch name', default='main')
        })),
        'script': fields.String(description='Python script to run', default='app.py'),
        'cron': fields.String(description='Cron pattern for restart', default=' '),
        'auto_restart': fields.Boolean(description='Enable auto-restart', default=False),
        'max_restarts': fields.String(description='Maximum number of restarts', default='3'),
        'watch': fields.String(description='Enable file watching', default='False'),
        'max_memory_restart': fields.String(description='Memory limit for restart', default='1G'),
        'env_vars': fields.Nested(env_config_model, description='Environment variables')
    })

    # Model for updating process configuration
    update_config_model = api.model('UpdateConfig', {
        'script': fields.String(description='Python script to run'),
        'cron': fields.String(description='Cron pattern for restart'),
        'auto_restart': fields.Boolean(description='Enable auto-restart'),
        'env_vars': fields.Nested(env_config_model, description='Environment variables')
    })

    # Model for process paths and configuration
    process_paths_model = api.model('ProcessPaths', {
        'base_folder': fields.String(description='Base process folder'),
        'process_folder': fields.String(description='Current process folder'),
        'venv_path': fields.String(description='Virtual environment path'),
        'logs_path': fields.String(description='Logs directory path'),
        'config_file': fields.String(description='PM2 config file path'),
        'out_log': fields.String(description='Output log file path'),
        'error_log': fields.String(description='Error log file path'),
        'pid_file': fields.String(description='PID file path')
    })

    # Full process details model
    process_details_model = api.model('ProcessDetails', {
        'process': fields.Nested(process_model, description='Process status information'),
        'paths': fields.Nested(process_paths_model, description='Process paths and configuration'),
        'config': fields.Nested(new_process_model, description='Process configuration')
    })

    # Response models for update operations
    update_response_model = api.model('UpdateResponse', {
        'message': fields.String(description='Status message'),
        'output': fields.String(description='Command output')
    })

    config_update_response_model = api.model('ConfigUpdateResponse', {
        'message': fields.String(description='Status message'),
        'config_file': fields.String(description='Updated config file path'),
        'reload_output': fields.String(description='Reload command output')
    })

    return {
        'process': process_model,
        'new_process': new_process_model,
        'update_config': update_config_model,
        'process_details': process_details_model,
        'monit': monit_model,
        'env_config': env_config_model,
        'process_paths': process_paths_model,
        'update_response': update_response_model,
        'config_update_response': config_update_response_model
    }