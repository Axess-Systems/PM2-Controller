import os
import json
import subprocess
import threading
import shutil
from pathlib import Path
from typing import Dict, Optional
import logging
import time
from core.config import Config
from core.exceptions import ProcessNotFoundError, ProcessAlreadyExistsError, PM2CommandError

class ProcessManager:
    """Service for managing PM2 processes and their configurations"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._command_locks = {}  # Process-specific locks
        self._global_lock = threading.Lock()
        self._lock_timeouts = {}  # Track lock timeouts

    def _get_process_lock(self, process_name: str) -> threading.Lock:
        """Get or create a process-specific lock"""
        with self._global_lock:
            if process_name not in self._command_locks:
                self._command_locks[process_name] = threading.Lock()
                self._lock_timeouts[process_name] = time.time()
            return self._command_locks[process_name]
        
    def _clear_stale_lock(self, process_name: str):
        """Clear a potentially stale lock"""
        with self._global_lock:
            if process_name in self._lock_timeouts:
                last_time = self._lock_timeouts[process_name]
                if time.time() - last_time > 300:  # 5 minutes timeout
                    self.logger.warning(f"Clearing stale lock for process {process_name}")
                    if process_name in self._command_locks:
                        del self._command_locks[process_name]
                    if process_name in self._lock_timeouts:
                        del self._lock_timeouts[process_name]
                        


    def _create_pm2_config(self, name: str, repo_url: str, script: str = 'app.py', 
                        cron: str = None, auto_restart: bool = True, env_vars: Dict[str, str] = None) -> Path:
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

        self.logger.debug(f"Creating PM2 config at {config_path}")
        with open(config_path, 'w') as f:
            f.write(config_content)
        
        return config_path



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

    def update_config(self, name: str, config_data: Dict) -> Dict:
        """Update process configuration"""
        try:
            if not Path(f"/home/pm2/pm2-configs/{name}.config.js").exists():
                raise ProcessNotFoundError(f"Process {name} not found")
            
            with self._get_process_lock(name):
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
                result = self._run_pm2_deploy_command(name, f"exec pm2 reload {name}")
                if not result["success"]:
                    raise PM2CommandError(f"Reload failed: {result['error']}")
                
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
            with self._get_process_lock(name):
                # First check if process exists and is running
                try:
                    process_info = json.loads(subprocess.run(
                        f"{self.config.PM2_BIN} jlist",
                        shell=True,
                        capture_output=True,
                        text=True,
                        check=True
                    ).stdout)
                    
                    # Find our process
                    process = next((p for p in process_info if p['name'] == name), None)
                    if process and process.get('pm2_env', {}).get('status') == 'online':
                        raise PM2CommandError(
                            f"Process {name} is currently running. Please stop it first using 'pm2 stop {name}'"
                        )
                    
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
                        shutil.rmtree(process_dir)
                    
                    return {
                        "message": f"Process {name} deleted successfully"
                    }
                    
                except subprocess.CalledProcessError as e:
                    self.logger.error(f"Error checking PM2 process status: {str(e)}")
                    raise PM2CommandError(f"Failed to check process status: {str(e)}")
                
        except Exception as e:
            self.logger.error(f"Failed to delete process {name}: {str(e)}")
            raise  
        
    def _run_command(self, cmd: str, timeout: int = 300) -> Dict:
        """Run a shell command and handle the response"""
        try:
            self.logger.info(f"Running command: {cmd}")
            
            # Create a new session for the subprocess
            start_new_session = True if os.name != 'nt' else False
            
            process = subprocess.run(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                start_new_session=start_new_session,
                env=dict(os.environ, PM2_SILENT='true')
            )
            
            if process.returncode == 0:
                output = process.stdout.strip()
                self.logger.info(f"Command output: {output}")
                return {
                    "success": True,
                    "output": output
                }
            else:
                error_msg = process.stderr.strip() or process.stdout.strip() or "Unknown error"
                self.logger.error(f"Command failed: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg
                }
                
        except subprocess.TimeoutExpired as e:
            error_msg = f"Command timed out after {timeout} seconds"
            self.logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Error running command: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }


    def create_process(self, config_data: Dict) -> Dict:
        """Create a new PM2 process config file and set it up"""
        try:
            name = config_data['name']
            created_config = False
            
            # Check if process already exists
            if Path(f"/home/pm2/pm2-configs/{name}.config.js").exists():
                raise ProcessAlreadyExistsError(f"Process {name} already exists")
            
            # Create config file first
            config_path = self._create_pm2_config(
                name=name,
                repo_url=config_data['repository']['url'],
                script=config_data.get('script', 'app.py'),
                cron=config_data.get('cron'),
                auto_restart=config_data.get('auto_restart', True),
                env_vars=config_data.get('env_vars')
            )
            created_config = True
            
            # Run setup
            self.logger.info(f"Setting up process {name}...")
            setup_result = self._run_pm2_deploy_command(name, "setup")
            if not setup_result["success"]:
                raise PM2CommandError(f"Setup failed: {setup_result.get('error', 'Unknown error')}")
            
            time.sleep(2)  # Small delay between setup and deploy
            
            # Run deploy
            self.logger.info(f"Deploying process {name}...")
            deploy_result = self._run_pm2_deploy_command(name)
            if not deploy_result["success"]:
                raise PM2CommandError(f"Deployment failed: {deploy_result.get('error', 'Unknown error')}")
            
            return {
                "message": f"Process {name} created and deployed successfully",
                "config_file": str(config_path),
                "setup_output": setup_result["output"],
                "deploy_output": deploy_result["output"]
            }
            
        except Exception as e:
            self.logger.error(f"Failed to create process {name}: {str(e)}")
            # Cleanup on failure
            if created_config:
                try:
                    config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
                    if config_path.exists():
                        config_path.unlink()
                    process_dir = Path(f"/home/pm2/pm2-processes/{name}")
                    if process_dir.exists():
                        shutil.rmtree(process_dir)
                except Exception as cleanup_error:
                    self.logger.error(f"Cleanup failed: {str(cleanup_error)}")
            raise

    def update_process(self, name: str) -> Dict:
        """Update an existing process using PM2 deploy"""
        try:
            if not Path(f"/home/pm2/pm2-configs/{name}.config.js").exists():
                raise ProcessNotFoundError(f"Process {name} not found")
            
            # Run update
            self.logger.info(f"Updating process {name}...")
            result = self._run_pm2_deploy_command(name, "update")
            if not result["success"]:
                raise PM2CommandError(f"Update failed: {result['error']}")
            
            return {
                "message": f"Process {name} updated successfully",
                "output": result["output"]
            }
            
        except Exception as e:
            self.logger.error(f"Failed to update process {name}: {str(e)}")
            raise

    def _run_pm2_deploy_command(self, process_name: str, command: str = "") -> Dict:
        """Run PM2 deploy command with retries and force flag"""
        config_path = f"/home/pm2/pm2-configs/{process_name}.config.js"
        
        # Build command
        cmd = f"pm2 deploy {config_path} production"
        if command:
            cmd += f" {command}"
        cmd += " --force"
        
        for attempt in range(3):  # Try up to 3 times
            result = self._run_command(cmd)
            if result["success"]:
                return result
                
            if attempt < 2:  # If not the last attempt
                self.logger.warning(f"Retrying command... ({attempt + 1}/3)")
                time.sleep(5)
        
        return result