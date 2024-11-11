import os
import json
import subprocess
from pathlib import Path
from typing import Dict, Optional
import logging
from core.config import Config
from core.exceptions import ProcessNotFoundError, ProcessAlreadyExistsError, PM2CommandError

class ProcessManager:
    """Service for managing PM2 processes and their configurations"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
    
    def _create_pm2_config(self, name: str, repo_url: str, script: str = 'app.py', 
                          cron: str = '', auto_restart: bool = True, env_vars: Dict[str, str] = None) -> Path:
        """Create PM2 config file with the specified template"""
        config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
        
        # Use provided env vars or defaults
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

        # Format environment config
        env_config_str = ',\n    '.join(f'{key}: "{value}"' for key, value in default_env.items())
        
        config_content = f'''// Process Configuration
const processName = '{name}';
const repoUrl = '{repo_url}';
const processScript = `{script}`;
const processCron = `{cron}`;
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
        cwd: processFolder,
        interpreter: `${{venvPath}}/bin/python3`,
        env: envConfig,
        autorestart: autoRestart,
        cron_restart: processCron,
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
            "pre-deploy": `rm -rf ${{venvPath}} && mkdir -p ${{logsPath}}`,
            "post-deploy": `mkdir -p ${{venvPath}} && \\
                git reset --hard && \\
                git pull origin main && \\
                python3 -m venv ${{venvPath}} && \\
                ${{venvPath}}/bin/pip install --upgrade pip && \\
                if [ -f ${{processFolder}}/requirements.txt ]; then \\
                  ${{venvPath}}/bin/pip install -r ${{processFolder}}/requirements.txt; \\
                fi && \\
                pm2 start ${{configFile}} && \\
                pm2 stop ${{configFile}} && \\
                pm2 start ${{processName}} --env production && \\
                pm2 save`
        }}
    }}
}};'''

        self.logger.debug(f"Creating PM2 config at {config_path}")
        with open(config_path, 'w') as f:
            f.write(config_content)
        
        return config_path
    
    def _run_pm2_deploy_command(self, process_name: str, command: str) -> Dict:
        """Run PM2 deploy command and handle errors"""
        try:
            config_path = f"/home/pm2/pm2-configs/{process_name}.config.js"
            cmd = f"pm2 deploy {config_path} production {command} --force"
            
            self.logger.info(f"Running PM2 deploy command: {cmd}")
            result = subprocess.run(
                cmd,
                shell=True,
                check=True,
                capture_output=True,
                text=True
            )
            
            output = result.stdout.strip()
            self.logger.info(f"PM2 deploy command output: {output}")
            
            return {
                "message": f"Command '{command}' executed successfully for {process_name}",
                "output": output
            }
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip()
            self.logger.error(f"PM2 deploy command failed: {error_msg}")
            raise PM2CommandError(f"Deploy command failed: {error_msg}")
    
    def get_process_config(self, name: str) -> Dict:
        """Get current process configuration"""
        config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
        
        if not config_path.exists():
            raise ProcessNotFoundError(f"Configuration for process {name} not found")
            
        try:
            with open(config_path, 'r') as f:
                content = f.read()
                
            # Extract values using simple parsing
            config = {}
            
            # Extract basic settings
            for line in content.split('\n'):
                if line.startswith('const processName'):
                    config['name'] = line.split("'")[1]
                elif line.startswith('const repoUrl'):
                    config['repository'] = {'url': line.split("'")[1]}
                elif line.startswith('const processScript'):
                    config['script'] = line.split('`')[1]
                elif line.startswith('const processCron'):
                    config['cron'] = line.split('`')[1]
                elif line.startswith('const autoRestart'):
                    config['auto_restart'] = 'true' in line.lower()
                    
            # Extract environment config
            env_start = content.find('const envConfig = {')
            if env_start != -1:
                env_end = content.find('};', env_start)
                env_block = content[env_start:env_end]
                env_vars = {}
                for line in env_block.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip().strip(',').strip('"\'')
                        if key:
                            env_vars[key] = value
                config['env_vars'] = env_vars
            
            return config
            
        except Exception as e:
            self.logger.error(f"Error reading config for {name}: {str(e)}")
            raise
    
    def create_process(self, name: str, repo_url: str, script: str = 'app.py', 
                      cron: str = '', auto_restart: bool = True, env_vars: Dict[str, str] = None) -> Dict:
        """Create a new PM2 process config file and set it up"""
        try:
            # Create config file
            config_path = self._create_pm2_config(
                name=name,
                repo_url=repo_url,
                script=script,
                cron=cron,
                auto_restart=auto_restart,
                env_vars=env_vars
            )
            
            # Run setup
            setup_result = self._run_pm2_deploy_command(name, "setup")
            
            # Run deploy
            deploy_result = self._run_pm2_deploy_command(name, "")
            
            return {
                "message": f"Process {name} created and deployed successfully",
                "config_file": str(config_path),
                "setup_output": setup_result["output"],
                "deploy_output": deploy_result["output"]
            }
            
        except Exception as e:
            self.logger.error(f"Failed to create process {name}: {str(e)}")
            raise
    
    def update_process(self, name: str) -> Dict:
        """Update an existing process using PM2 deploy"""
        try:
            if not Path(f"/home/pm2/pm2-configs/{name}.config.js").exists():
                raise ProcessNotFoundError(f"Process {name} not found")
                
            result = self._run_pm2_deploy_command(name, "update")
            
            return {
                "message": f"Process {name} updated successfully",
                "output": result["output"]
            }
            
        except Exception as e:
            self.logger.error(f"Failed to update process {name}: {str(e)}")
            raise
            
    def update_config(self, name: str, config_data: Dict) -> Dict:
        """Update process configuration"""
        try:
            if not Path(f"/home/pm2/pm2-configs/{name}.config.js").exists():
                raise ProcessNotFoundError(f"Process {name} not found")
            
            # Get current config
            current_config = self.get_process_config(name)
            
            # Create updated config
            config_path = self._create_pm2_config(
                name=name,
                repo_url=current_config['repository']['url'],
                script=config_data.get('script', current_config.get('script', 'app.py')),
                cron=config_data.get('cron', current_config.get('cron', '')),
                auto_restart=config_data.get('auto_restart', current_config.get('auto_restart', True)),
                env_vars=config_data.get('env_vars', current_config.get('env_vars', {}))
            )
            
            # Reload the process
            result = self._run_pm2_deploy_command(name, "exec pm2 reload " + name)
            
            return {
                "message": f"Configuration for {name} updated successfully",
                "config_file": str(config_path),
                "reload_output": result["output"]
            }
            
        except Exception as e:
            self.logger.error(f"Failed to update config for {name}: {str(e)}")
            raise
    
    def delete_process(self, name: str) -> Dict:
        """Delete a process and its configuration"""
        try:
            config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            process_dir = Path(f"/home/pm2/pm2-processes/{name}")
            
            # Delete from PM2
            cmd = f"pm2 delete {name}"
            try:
                subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError:
                self.logger.warning(f"Process {name} was not running in PM2")
            
            # Remove config file
            if config_path.exists():
                config_path.unlink()
            
            # Remove process directory
            if process_dir.exists():
                import shutil
                shutil.rmtree(process_dir)
            
            return {
                "message": f"Process {name} deleted successfully"
            }
            
        except Exception as e:
            self.logger.error(f"Failed to delete process {name}: {str(e)}")
            raise