# services/pm2/config.py

from typing import Dict, Optional
from pathlib import Path
import logging

class PM2Config:
    """Handles PM2 configuration file generation and management"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def generate_config(
        self,
        name: str,
        repo_url: str,
        script: str = 'app.py',
        cron: Optional[str] = None,
        auto_restart: bool = True,
        env_vars: Optional[Dict[str, str]] = None
    ) -> Path:
        """Generate PM2 config file with the specified template"""
        config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
        
        default_env = {
            "PORT": "5001",
            "HOST": "0.0.0.0",
            "DEBUG": "False",
            "LOG_LEVEL": "INFO",
            "PM2_BIN": "pm2",
            "MAX_LOG_LINES": "1000",
            "COMMAND_TIMEOUT": "30",
            "MAX_RETRIES": "3",
            "RETRY_DELAY": "1"
        }
        
        if env_vars:
            default_env.update(env_vars)

        env_config_str = ',\n    '.join(f'{key}: "{value}"' for key, value in default_env.items())
        
        config_content = self._get_config_template(
            name=name,
            repo_url=repo_url,
            script=script,
            cron=cron,
            auto_restart=auto_restart,
            env_config_str=env_config_str
        )

        self.logger.debug(f"Creating PM2 config at {config_path}")
        with open(config_path, 'w') as f:
            f.write(config_content)
        
        return config_path

    def _get_config_template(self, name: str, repo_url: str, script: str,
                           cron: Optional[str], auto_restart: bool,
                           env_config_str: str) -> str:
        """Get the PM2 config file template"""
        return f'''// Process Configuration
    const processName = '{name}';
    const repoUrl = '{repo_url}';
    const processScript = `{script}`;
    const autoRestart = {str(auto_restart).lower()};
    const envConfig = {{
        {env_config_str}
    }};

    // Static Configuration
    const baseFolder = `/home/pm2/pm2-processes/${{processName}}`;
    const processFolder = `${{baseFolder}}/current`;
    const venvPath = `${{baseFolder}}/venv`;
    const logsPath = `${{baseFolder}}/logs`;
    const configFile = `/home/pm2/pm2-configs/${{processName}}.config.js`;

    module.exports = {{
        apps: [{{
            name: processName,
            script: processScript,
            args: `app:application --bind ${{envConfig.HOST}}:${{envConfig.PORT}} --chdir ${{processFolder}} --worker-class=gthread --workers=1 --threads=4 --timeout=120`,
            cwd: processFolder,
            env: envConfig,
            autorestart: autoRestart,
            {f'cron_restart: "{cron}",' if cron and cron.strip() else ''}
            max_restarts: 3,
            watch: true,
            ignore_watch: [
                "venv",
                "*.pyc",
                "__pycache__",
                "*.log"
            ],
            max_memory_restart: "1G",
            log_date_format: "YYYY-MM-DD HH:mm:ss Z",
            error_file: `${{logsPath}}/${{processName}}-error.log`,
            out_file: `${{logsPath}}/${{processName}}-out.log`,
            combine_logs: true,
            merge_logs: true,
            time: true,
            pid_file: `${{logsPath}}/${{processName}}.pid`
        }}],

        deploy: {{
            production: {{
                user: "pm2",
                host: ["localhost"],
                ref: "main",
                repo: repoUrl,
                path: baseFolder,
                "pre-setup": `mkdir -p ${{baseFolder}}`,
                "pre-deploy": `mkdir -p ${{logsPath}} && rm -rf ${{venvPath}}`,
                "post-deploy": `cd ${{processFolder}} && \\
                    git reset --hard && \\
                    git pull origin main && \\
                    python3 -m venv ${{venvPath}} && \\
                    ${{venvPath}}/bin/pip install --upgrade pip && \\
                    if [ -f requirements.txt ]; then \\
                        ${{venvPath}}/bin/pip install -r requirements.txt; \\
                    fi && \\
                    pm2 start ${{configFile}}`
            }}
        }}
    }};'''