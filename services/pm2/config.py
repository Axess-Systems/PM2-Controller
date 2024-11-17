# services/pm2/config.py
import logging
from pathlib import Path
from typing import Dict, Optional


# services/pm2/config.py
class PM2Config:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def generate_config(self, name: str, repo_url: str, script: str = 'main.py', 
                    branch: str = "main", cron: str = None, auto_restart: bool = True, 
                    env_vars: Dict[str, str] = None) -> Path:
        """Create PM2 config file
        
        Args:
            name: Process name
            repo_url: Git repository URL
            script: Python script to run
            branch: Git branch
            cron: Cron schedule for restart
            auto_restart: Enable auto restart
            env_vars: Environment variables
            
        Returns:
            Path: Path to generated config file
        """
        config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
        
        # Use provided env vars or defaults
        default_env = {
            "PORT": "5001",
            "HOST": "0.0.0.0"
        }
        
        if env_vars:
            default_env.update(env_vars)

        env_config_str = ',\n    '.join(f'{key}: "{value}"' for key, value in default_env.items())
        
        # Create the post-deploy command without string template and replace
        post_deploy_command = (
            f"cd ${{processFolder}} && "
            f"git reset --hard && "
            f"git checkout {branch} && "
            f"git pull origin {branch} && "
            f"python3 -m venv ${{venvPath}} && "
            f"${{venvPath}}/bin/pip install --upgrade pip && "
            f"if [ -f requirements.txt ]; then ${{venvPath}}/bin/pip install -r requirements.txt; fi"
        )

        config_content = f'''// Process Configuration
const processName = '{name}';
const repoUrl = '{repo_url}';
const processScript = '{script}';
const autoRestart = {str(auto_restart).lower()};
const envConfig = {{
    {env_config_str}
}};

// Static Configuration
const baseFolder = `/home/pm2/pm2-processes/${processName}`;
const processFolder = `${baseFolder}/current`;
const venvPath = `${baseFolder}/venv`;
const logsPath = `${baseFolder}/logs`;
const configFile = `/home/pm2/pm2-configs/${processName}.config.js`;

module.exports = {{
    apps: [{{
        name: processName,
        script: `${venvPath}/bin/python`,
        args: `${processScript}`,
        cwd: processFolder,
        env: envConfig,
        autorestart: autoRestart,
        {f'cron_restart: "{cron}",' if cron and cron.strip() else ''}
        max_restarts: 3,
        watch: false,
        ignore_watch: [
            "venv",
            "*.pyc",
            "__pycache__",
            "*.log"
        ],
        max_memory_restart: "1G",
        log_date_format: "YYYY-MM-DD HH:mm:ss Z",
        error_file: `${logsPath}/${processName}-error.log`,
        out_file: `${logsPath}/${processName}-out.log`,
        combine_logs: true,
        merge_logs: true,
        time: true,
        pid_file: `${logsPath}/${processName}.pid`
    }}],

    deploy: {{
        production: {{
            user: "pm2",
            host: ["localhost"],
            ref: "{branch}",
            repo: repoUrl,
            path: baseFolder,
            "pre-setup": `mkdir -p ${baseFolder}`,
            "pre-deploy": `mkdir -p ${logsPath} && rm -rf ${venvPath}`,
            "post-deploy": "{post_deploy_command}"
        }}
    }}
}};'''

        self.logger.debug(f"Creating PM2 config at {config_path}")
        with open(config_path, 'w') as f:
            f.write(config_content)
        
        return config_path

