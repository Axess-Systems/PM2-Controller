# services/process/manager.py
import json
import os
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict
import sqlite3
from datetime import datetime

from core.config import Config
from core.exceptions import (
    PM2CommandError,
    ProcessNotFoundError,
    ProcessAlreadyExistsError,
)
from services.pm2 import PM2Service, PM2Commands

class ProcessManager:
    def __init__(self, config: Config, logger: logging.Logger):
        """Initialize ProcessManager"""
        self.config = config
        self.logger = logger
        self.pm2_service = PM2Service(config, logger)
        self.pm2_commands = PM2Commands(config, logger)

    def create_process(self, config_data: Dict) -> Dict:
        """Create a new PM2 process"""
        try:
            name = config_data["name"]
            self.logger.info(f"Creating new process: {name}")
            
            # Setup paths
            base_path = Path("/home/pm2")
            config_dir = base_path / "pm2-configs"
            process_dir = base_path / "pm2-processes" / name
            logs_dir = process_dir / "logs"
            current_dir = process_dir / "current"
            venv_path = process_dir / "venv"

            # Create directories
            for directory in [config_dir, process_dir, logs_dir, current_dir]:
                directory.mkdir(parents=True, exist_ok=True)

            # Clone repository
            repo_url = config_data['repository']['url']
            branch = config_data['repository'].get('branch', 'main')
            
            self.logger.debug(f"Cloning repository {repo_url} branch {branch}")
            clone_result = os.system(f"git clone -b {branch} {repo_url} {current_dir}")
            if clone_result != 0:
                raise PM2CommandError("Git clone failed")

            # Setup virtual environment
            self.logger.debug(f"Creating virtual environment at {venv_path}")
            venv_result = os.system(f"python3 -m venv {venv_path}")
            if venv_result != 0:
                raise PM2CommandError("Virtual environment creation failed")

            # Install dependencies if requirements.txt exists
            requirements_file = current_dir / "requirements.txt"
            if requirements_file.exists():
                self.logger.debug("Installing dependencies")
                pip_result = os.system(f"{venv_path}/bin/pip install -r {requirements_file}")
                if pip_result != 0:
                    raise PM2CommandError("Dependencies installation failed")

            # Generate PM2 config
            config_file = config_dir / f"{name}.config.js"
            
            # Handle cron pattern - only include if it's a valid pattern
            cron_value = config_data.get('cron')
            if cron_value and cron_value.strip() and re.match(r'^(\S+\s+){4,5}\S+$', cron_value):
                cron_config = f'cron_restart: "{cron_value}",'
            else:
                cron_config = ''
            
            config_content = f'''// Process Configuration
    const processName = '{name}';
    const repoUrl = '{repo_url}';
    const processScript = `{config_data.get('script', 'app.py')}`;
    const autoRestart = {str(config_data.get('auto_restart', False)).lower()};
    const max_restarts = `{config_data.get('max_restarts', '3')}`;
    const watch = `{config_data.get('watch', 'False')}`;
    const max_memory_restart = `{config_data.get('max_memory_restart', '1G')}`;
    const envConfig = {json.dumps(config_data.get('env_vars', {
        'PORT': '5001',
        'HOST': '0.0.0.0',
        'DEBUG': 'False',
        'LOG_LEVEL': 'DEBUG',
        'PM2_BIN': 'pm2',
        'MAX_LOG_LINES': '1000',
        'COMMAND_TIMEOUT': '120',
        'MAX_RETRIES': '3',
        'RETRY_DELAY': '1'
    }), indent=4)};

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
            args: `app:application --worker-class=gthread --workers=1 --threads=4 --timeout=120`,
            interpreter: `${{venvPath}}/bin/python3`,
            env: envConfig,
            autorestart: autoRestart,
            {cron_config}
            max_restarts: max_restarts,
            watch: watch,
            ignore_watch: [
                "venv",
                "*.pyc",
                "__pycache__",
                "*.log"
            ],
            max_memory_restart: max_memory_restart,
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
                ref: "{branch}",
                repo: repoUrl,
                path: baseFolder,
                "pre-setup": `mkdir -p ${{baseFolder}}`,
                "pre-deploy": `rm -rf ${{venvPath}} && mkdir -p ${{logsPath}}`,
                "post-deploy": `mkdir -p ${{venvPath}} && \\
                    git reset --hard && \\
                    git pull origin {branch} && \\
                    python3 -m venv ${{venvPath}} && \\
                    ${{venvPath}}/bin/pip install --upgrade pip && \\
                    if [ -f ${{processFolder}}/requirements.txt ]; then \\
                    ${{venvPath}}/bin/pip install -r ${{processFolder}}/requirements.txt; \\
                    fi && \\
                    pm2 start ${{configFile}}`
            }}
        }}
    }};'''

            config_file.write_text(config_content)

            # Start the process in a detached way
            self.logger.debug(f"Starting process with PM2: {name}")
            try:
                start_script = process_dir / "start.sh"
                start_script_content = f'''#!/bin/bash
    {self.config.PM2_BIN} start {config_file}
    {self.config.PM2_BIN} save --force
    '''
                start_script.write_text(start_script_content)
                os.chmod(start_script, 0o755)

                # Execute the start script in the background
                subprocess.Popen(
                    ["/bin/bash", str(start_script)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True
                )

                self.logger.info(f"Process {name} created successfully")
                return {
                    "success": True,
                    "message": f"Process {name} created successfully",
                    "process_name": name,
                    "config_file": str(config_file)
                }

            except Exception as e:
                raise PM2CommandError(f"PM2 start failed: {str(e)}")

        except Exception as e:
            self.logger.error(f"Process creation failed: {str(e)}", exc_info=True)
            self._cleanup_failed_process(name, process_dir)
            raise PM2CommandError(f"Process creation failed: {str(e)}")

    def _cleanup_failed_process(self, name: str, process_dir: Path):
        """Clean up resources after failed process creation"""
        try:
            # Try to remove from PM2
            try:
                self.pm2_commands.execute(f"delete {name}", retry=False)
                self.pm2_commands.execute("save", retry=False)
            except:
                pass

            # Remove process directory
            if process_dir.exists():
                shutil.rmtree(process_dir)

        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}")


            
    def delete_process(self, name: str) -> Dict:
        """Delete a process"""
        try:
            self.logger.info(f"Deleting process: {name}")
            process_dir = Path(f"/home/pm2/pm2-processes/{name}")

            # Delete from PM2
            try:
                self.pm2_commands.execute(f"delete {name}")
                self.pm2_commands.execute("save")
            except Exception as e:
                self.logger.warning(f"PM2 deletion warning: {str(e)}")
            
            # Remove process directory
            if process_dir.exists():
                shutil.rmtree(process_dir)

            return {
                "success": True,
                "message": f"Process {name} deleted successfully"
            }

        except Exception as e:
            self.logger.error(f"Failed to delete process {name}: {str(e)}")
            raise PM2CommandError(f"Error deleting process {name}: {str(e)}")     
        
    def _generate_pm2_config(self, name: str, script: str, current_dir: Path, 
                           venv_path: Path, logs_dir: Path, env_vars: Dict, 
                           auto_restart: bool) -> str:
        """Generate PM2 configuration file content"""
        return f'''module.exports = {{
    apps: [{{
        name: "{name}",
        script: "{venv_path}/bin/python",
        args: "{script}",
        cwd: "{current_dir}",
        env: {json.dumps(env_vars)},
        autorestart: {str(auto_restart).lower()},
        watch: false,
        ignore_watch: [
            "venv",
            "*.pyc",
            "__pycache__",
            "*.log"
        ],
        max_memory_restart: "1G",
        error_file: "{logs_dir}/{name}-error.log",
        out_file: "{logs_dir}/{name}-out.log",
        merge_logs: true,
        time: true,
        log_date_format: "YYYY-MM-DD HH:mm:ss Z"
    }}]
}};'''


    def get_process_config(self, name: str) -> Dict:
        """Get process configuration
        
        Args:
            name: Name of the process
            
        Returns:
            Dict containing process configuration
            
        Raises:
            ProcessNotFoundError: If process doesn't exist
        """
        try:
            self.logger.debug(f"Getting config for process: {name}")
            config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            
            if not config_path.exists():
                raise ProcessNotFoundError(f"Config file not found for process {name}")
            
            with open(config_path, 'r') as f:
                config_content = f.read()
                
            self.logger.debug(f"Retrieved config for process {name}")
            return {
                "success": True,
                "config_file": str(config_path),
                "content": config_content
            }
            
        except ProcessNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to get config for process {name}: {str(e)}", exc_info=True)
            raise PM2CommandError(f"Failed to get process config: {str(e)}")

    def update_process(self, name: str) -> Dict:
        """Update process code and restart with proper cleanup
        
        Args:
            name: Name of the process
            
        Returns:
            Dict containing update status and outputs
            
        Raises:
            ProcessNotFoundError: If process doesn't exist
            PM2CommandError: If update fails
        """
        try:
            self.logger.info(f"Starting update process for: {name}")
            
            config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            if not config_path.exists():
                raise ProcessNotFoundError(f"Config file not found for {name}")

            outputs = {}

            # Step 1: Kill the process to ensure clean state
            try:
                kill_result = subprocess.run(
                    f"{self.config.PM2_BIN} kill",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=self.config.COMMAND_TIMEOUT
                )
                outputs['kill_output'] = kill_result.stdout
                if kill_result.returncode != 0:
                    self.logger.warning(f"PM2 kill warning: {kill_result.stderr}")
            except Exception as e:
                self.logger.warning(f"PM2 kill warning: {str(e)}")

            # Step 2: Run PM2 deploy with update action
            deploy_cmd = f"{self.config.PM2_BIN} deploy {config_path} production update --force"
            deploy_result = subprocess.run(
                deploy_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300  # Longer timeout for deploy
            )
            
            if deploy_result.returncode != 0:
                raise PM2CommandError(f"Deploy failed: {deploy_result.stderr}")
            
            outputs['deploy_output'] = deploy_result.stdout

            # Step 3: Verify and start the process
            try:
                # Start with the config file
                start_result = subprocess.run(
                    f"{self.config.PM2_BIN} start {config_path}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=self.config.COMMAND_TIMEOUT
                )
                
                if start_result.returncode != 0:
                    raise PM2CommandError(f"Process start failed: {start_result.stderr}")
                
                outputs['start_output'] = start_result.stdout

                # Save PM2 process list
                save_result = subprocess.run(
                    f"{self.config.PM2_BIN} save",
                    shell=True,
                    capture_output=True,
                    text=True
                )
                
                if save_result.returncode != 0:
                    self.logger.warning(f"PM2 save warning: {save_result.stderr}")
                
                outputs['save_output'] = save_result.stdout

                return {
                    "success": True,
                    "message": f"Process {name} updated successfully",
                    "process_name": name,
                    "outputs": outputs
                }

            except Exception as e:
                self.logger.error(f"Post-deploy process start failed: {str(e)}")
                # Try to restore the process in case of startup failure
                try:
                    subprocess.run(
                        f"{self.config.PM2_BIN} start {config_path}",
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=self.config.COMMAND_TIMEOUT
                    )
                except Exception as restore_error:
                    self.logger.error(f"Failed to restore process after failed update: {str(restore_error)}")
                raise PM2CommandError(f"Process update failed: {str(e)}")
                
        except Exception as e:
            self.logger.error(f"Failed to update process {name}: {str(e)}", exc_info=True)
            raise PM2CommandError(f"Process update failed: {str(e)}")
    
    def update_config(self, name: str, config_data: Dict) -> Dict:
        """Update process configuration by modifying specific configurations
        
        Args:
            name: Name of the process
            config_data: New configuration data
            
        Returns:
            Dict containing update status
            
        Raises:
            ProcessNotFoundError: If process doesn't exist
            PM2CommandError: If update fails
        """
        try:
            self.logger.info(f"Updating configuration for process: {name}")
            self.logger.debug(f"New configuration: {json.dumps(config_data, indent=2)}")

            # Check if process exists and get current process info
            process = self.pm2_service.get_process(name)
            
            # Get current config file
            config_file = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            if not config_file.exists():
                raise ProcessNotFoundError(f"Config file not found for {name}")

            # Create backup of current config
            backup_file = config_file.with_suffix('.backup')
            shutil.copy2(config_file, backup_file)

            try:
                with open(config_file, 'r') as f:
                    config_content = f.read()

                # Update config content using regex patterns
                updated_content = config_content

                # Update script if provided
                if 'script' in config_data:
                    script_pattern = r'(script:\s*[`\'"])(.*?)([`\'"])'
                    if re.search(script_pattern, updated_content):
                        updated_content = re.sub(script_pattern, 
                                            rf'\1{config_data["script"]}\3', 
                                            updated_content)

                # Update cron if provided
                if 'cron' in config_data:
                    cron_pattern = r'(cron_restart:\s*[\'"])(.*?)([\'"])'
                    if re.search(cron_pattern, updated_content):
                        updated_content = re.sub(cron_pattern, 
                                            rf'\1{config_data["cron"]}\3', 
                                            updated_content)
                    elif config_data['cron']:  # Add cron if it doesn't exist
                        updated_content = updated_content.replace(
                            'watch: false,',
                            f'watch: false,\n        cron_restart: "{config_data["cron"]}",')

                # Update auto_restart if provided
                if 'auto_restart' in config_data:
                    auto_restart_pattern = r'(autorestart:\s*)(true|false)'
                    updated_content = re.sub(auto_restart_pattern, 
                                        rf'\1{str(config_data["auto_restart"]).lower()}', 
                                        updated_content)

                # Update environment variables if provided
                if 'env_vars' in config_data and config_data['env_vars']:
                    env_vars = config_data['env_vars']
                    env_vars_str = ',\n    '.join(f'{key}: "{value}"' 
                                                for key, value in env_vars.items())
                    
                    # Find the envConfig section
                    env_pattern = r'(const\s+envConfig\s*=\s*{)(.*?)(};)'
                    if re.search(env_pattern, updated_content, re.DOTALL):
                        updated_content = re.sub(env_pattern, 
                                            rf'\1\n    {env_vars_str}\n\3', 
                                            updated_content,
                                            flags=re.DOTALL)

                # Write updated config
                with open(config_file, 'w') as f:
                    f.write(updated_content)

                # Reload the process with new config
                reload_result = subprocess.run(
                    f"pm2 reload {name}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=True
                )

                # Save PM2 process list
                save_result = subprocess.run(
                    "pm2 save",
                    shell=True,
                    capture_output=True,
                    text=True
                )

                if save_result.returncode != 0:
                    self.logger.warning(f"PM2 save warning: {save_result.stderr}")

                return {
                    "success": True,
                    "message": f"Configuration updated for process {name}",
                    "config_file": str(config_file),
                    "reload_output": reload_result.stdout,
                    "save_output": save_result.stdout
                }

            except Exception as e:
                # Restore backup on failure
                if backup_file.exists():
                    shutil.copy2(backup_file, config_file)
                    
                    # Try to reload with old config
                    try:
                        subprocess.run(
                            f"pm2 reload {name}",
                            shell=True,
                            capture_output=True,
                            text=True,
                            check=True
                        )
                    except Exception as reload_error:
                        self.logger.error(f"Failed to reload process with restored config: {str(reload_error)}")
                    
                raise PM2CommandError(f"Failed to update config: {str(e)}")

            finally:
                # Clean up backup
                if backup_file.exists():
                    backup_file.unlink()

        except ProcessNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to update config for {name}: {str(e)}", exc_info=True)
            raise PM2CommandError(f"Config update failed: {str(e)}")
        
    def log_status(self):
        """Log current status of PM2 processes"""
        try:
            processes = self.pm2_service.list_processes()
            if not processes:
                self.logger.warning("No processes found to log")
                return

            conn = sqlite3.connect(self.config.DB_PATH)
            cursor = conn.cursor()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            for process in processes:
                try:
                    service_name = process.get("name", "Unknown")
                    pm2_env = process.get("pm2_env", {})
                    monit = process.get("monit", {})
                    
                    status_str = pm2_env.get("status", "stopped")
                    cpu_usage = monit.get("cpu", 0.0)
                    memory_usage = monit.get("memory", 0.0) / (1024 * 1024)  # Convert to MB
                    
                    # Determine status
                    has_error = status_str == "errored"
                    has_warning = status_str == "stopping" or status_str == "launching"
                    status_code = self._determine_status_code(status_str, has_error, has_warning)

                    cursor.execute('''
                        INSERT INTO service_status 
                        (service_name, timestamp, status, cpu_usage, memory_usage, has_error, has_warning)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        service_name, timestamp, status_code, cpu_usage, memory_usage,
                        1 if has_error else 0, 1 if has_warning else 0
                    ))
                    
                except Exception as e:
                    self.logger.error(f"Error logging process {service_name}: {str(e)}")
                    continue

            conn.commit()
            self.logger.debug(f"Successfully logged status for {len(processes)} processes")
                
        except Exception as e:
            self.logger.error(f"Error in log_status: {str(e)}")
        finally:
            if 'conn' in locals():
                conn.close()

    def _determine_status_code(self, status_str, has_error, has_warning):
        """Determine numeric status code from process state"""
        if status_str == "stopped":
            return 0
        elif has_error:
            return 3
        elif has_warning:
            return 1
        return 2    

    