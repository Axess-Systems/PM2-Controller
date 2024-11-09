from flask_restx import fields

def create_api_models(api):
    """Create and register API models for process management"""
    
    # Base environment variables model
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

    # Process monitoring stats model
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
        'status': fields.String(description='Process status'),
        'pm_uptime': fields.Integer(description='Process uptime'),
        'created_at': fields.Integer(description='Creation timestamp'),
        'pm_id': fields.Integer(description='PM2 process ID'),
        'restart_time': fields.Integer(description='Number of restarts', default=0),
        'unstable_restarts': fields.Integer(description='Number of unstable restarts', default=0),
        'exit_code': fields.Integer(description='Exit code'),
        
        # Environment
        'env': fields.Nested(base_env_model, description='Environment variables'),
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
        'repository': fields.Nested(api.model('Repository', {
            'url': fields.String(required=True, description='GitHub repository URL'),
            'project_dir': fields.String(required=True, description='Project directory name'),
            'branch': fields.String(required=True, description='Git branch name')
        })),
        'python': fields.Nested(api.model('PythonConfig', {
            'requirements_file': fields.String(description='Path to requirements.txt', default='requirements.txt'),
            'run_script': fields.String(description='Python script to run', default='app.py'),
            'arguments': fields.String(description='Additional script arguments', default=''),
            'variables': fields.Raw(description='Environment variables'),
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

    return {
        'process': process_model,
        'new_process': new_process_model,
        'pm2_env': pm2_env_model,
        'base_env': base_env_model,
        'monit': monit_model
    }