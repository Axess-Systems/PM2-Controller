from flask_restx import fields, Model

def create_api_models(api):
    """Create and register all API models"""
    
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
    })

    # Process monitoring stats model
    monit_model = api.model('Monitoring', {
        'memory': fields.Integer(description='Memory usage in bytes'),
        'cpu': fields.Float(description='CPU usage percentage')
    })

    # PM2 environment configuration model
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
        'status': fields.String(description='Process status'),
        'pm_uptime': fields.Integer(description='Process uptime'),
        'env': fields.Nested(base_env_model, description='Environment variables'),
    })

    # Main process model
    process_model = api.model('Process', {
        'pid': fields.Integer(description='Process ID'),
        'name': fields.String(description='Process name'),
        'pm2_env': fields.Nested(pm2_env_model, description='PM2 environment configuration'),
        'monit': fields.Nested(monit_model, description='Process monitoring statistics')
    })

    # New process creation model
    new_process_model = api.model('NewProcess', {
        'name': fields.String(required=True, description='Process name'),
        'repository': fields.Nested(api.model('Repository', {
            'url': fields.String(required=True, description='GitHub repository URL'),
            'project_dir': fields.String(required=True, description='Project directory name'),
            'branch': fields.String(required=True, description='Git branch name')
        })),
        'python': fields.Nested(api.model('PythonConfig', {
            'requirements_file': fields.String(description='Path to requirements.txt'),
            'run_script': fields.String(description='Python script to run'),
            'arguments': fields.String(description='Additional script arguments'),
            'variables': fields.Raw(description='Environment variables'),
            'smtp': fields.Nested(api.model('SMTPConfig', {
                'enabled': fields.Boolean(description='Enable SMTP')
            })),
        })),
        'pm2': fields.Nested(api.model('PM2Config', {
            'instances': fields.Integer(description='Number of instances'),
            'exec_mode': fields.String(description='Execution mode'),
            'watch': fields.Boolean(description='Enable watch mode'),
            'autorestart': fields.Boolean(description='Enable auto-restart')
        }))
    })

    return {
        'process': process_model,
        'new_process': new_process_model,
    }