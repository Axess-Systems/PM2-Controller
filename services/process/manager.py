# services/process/manager.py


# services/process/manager.py

import os
import json
import tempfile
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Dict
from datetime import datetime
from core.config import Config
from core.exceptions import ProcessAlreadyExistsError, PM2CommandError
from services.pm2.service import PM2Service
from core.config import Config
from core.exceptions import (
    PM2CommandError,
    ProcessNotFoundError,
    ProcessAlreadyExistsError,
)
from services.pm2.service import PM2Service

class ProcessManager:
    def __init__(self, config: Config, logger: logging.Logger):
        """Initialize ProcessManager
        
        Args:
            config: Application configuration instance
            logger: Logger instance for process management operations
        """
        self.config = config
        self.logger = logger
        self.pm2_service = PM2Service(config, logger)




    def create_process(self, config_data: Dict) -> Dict:
        """Create a new PM2 process using PM2's Python API"""
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
            
            # Check if process already exists
            config_path = config_dir / f"{name}.config.js"
            if config_path.exists():
                raise ProcessAlreadyExistsError(f"Process {name} already exists")

            # Create directories
            for directory in [config_dir, process_dir, logs_dir, current_dir]:
                directory.mkdir(parents=True, exist_ok=True)

            # Clone repository
            repo_url = config_data['repository']['url']
            branch = config_data['repository'].get('branch', 'main')
            
            os.system(f"git clone -b {branch} {repo_url} {current_dir}")

            # Setup virtual environment
            os.system(f"python3 -m venv {venv_path}")

            # Install dependencies if requirements.txt exists
            requirements_file = current_dir / "requirements.txt"
            if requirements_file.exists():
                os.system(f"{venv_path}/bin/pip install -r {requirements_file}")

            # Generate PM2 config
            config_content = self._generate_pm2_config(
                name=name,
                script=config_data.get('script', 'app.py'),
                current_dir=current_dir,
                venv_path=venv_path,
                logs_dir=logs_dir,
                env_vars=config_data.get('env_vars', {}),
                auto_restart=config_data.get('auto_restart', True)
            )

            config_path.write_text(config_content)

            # Start process using PM2's Python API
            pm2.api.start(str(config_path))

            self.logger.info(f"Process {name} created successfully")
            return {
                "success": True,
                "message": f"Process {name} created successfully",
                "process_name": name,
                "config_file": str(config_path),
            }

        except ProcessAlreadyExistsError:
            raise
        except Exception as e:
            self.logger.error(f"Process creation failed: {str(e)}", exc_info=True)
            # Cleanup on failure
            self._cleanup_failed_process(name, process_dir, config_path)
            raise PM2CommandError(f"Process creation failed: {str(e)}")

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

    def _cleanup_failed_process(self, name: str, process_dir: Path, config_path: Path):
        """Clean up resources after failed process creation"""
        try:
            # Try to remove from PM2
            try:
                pm2.api.delete(name)
            except:
                pass

            # Remove process directory
            if process_dir.exists():
                shutil.rmtree(process_dir)

            # Remove config file
            if config_path.exists():
                config_path.unlink()

        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}")
            
    def delete_process(self, name: str) -> Dict:
        """Delete a process and its associated files
        
        Args:
            name: Name of the process to delete
            
        Returns:
            Dict with deletion status
            
        Raises:
            PM2CommandError: If deletion fails
        """
        try:
            self.logger.info(f"Deleting process: {name}")
            
            config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            process_dir = Path(f"/home/pm2/pm2-processes/{name}")

            # Check PM2 process status
            try:
                process_list = json.loads(
                    subprocess.run(
                        f"{self.config.PM2_BIN} jlist",
                        shell=True,
                        capture_output=True,
                        text=True,
                        check=True,
                    ).stdout
                )

                process = next((p for p in process_list if p["name"] == name), None)
                if process:
                    if process.get("pm2_env", {}).get("status") == "online":
                        error_msg = f"Process {name} is currently running. Stop it first using 'pm2 stop {name}'"
                        self.logger.error(error_msg)
                        raise PM2CommandError(error_msg)
                        
                    self.logger.debug(f"Deleting PM2 process: {name}")
                    delete_result = subprocess.run(
                        f"{self.config.PM2_BIN} delete {name}",
                        shell=True,
                        capture_output=True,
                        text=True
                    )
                    if delete_result.returncode != 0:
                        self.logger.warning(f"PM2 delete returned non-zero: {delete_result.stderr}")
                    
            except subprocess.CalledProcessError as e:
                self.logger.warning(f"PM2 command failed: {e.stderr}")
            except json.JSONDecodeError as e:
                self.logger.warning(f"Failed to parse PM2 process list: {e}")

            # Clean up files
            if config_path.exists():
                self.logger.debug(f"Removing config file: {config_path}")
                config_path.unlink()
                
            if process_dir.exists():
                self.logger.debug(f"Removing process directory: {process_dir}")
                shutil.rmtree(process_dir)

            self.logger.info(f"Process {name} deleted successfully")
            return {
                "success": True,
                "message": f"Process {name} deleted successfully",
                "process_name": name
            }

        except Exception as e:
            self.logger.error(f"Failed to delete process {name}: {str(e)}", exc_info=True)
            raise PM2CommandError(f"Error deleting process {name}: {str(e)}")

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
        """Update process code and restart"""
        try:
            self.logger.info(f"Updating process: {name}")
            
            config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            process_dir = Path(f"/home/pm2/pm2-processes/{name}")
            current_dir = process_dir / "current"
            
            if not config_path.exists():
                raise ProcessNotFoundError(f"Config file not found for {name}")
            
            if not current_dir.exists():
                raise ProcessNotFoundError(f"Process directory not found: {current_dir}")

            # First do git pull in source directory
            source_dir = process_dir / "source"
            if source_dir.exists():
                git_pull = subprocess.run(
                    "git pull",
                    shell=True,
                    cwd=source_dir,
                    capture_output=True,
                    text=True
                )
                
                if git_pull.returncode != 0:
                    raise PM2CommandError(f"Git pull failed: {git_pull.stderr}")

                # Copy updated files to current directory
                shutil.rmtree(current_dir)
                shutil.copytree(source_dir, current_dir, dirs_exist_ok=True)

            # Install dependencies if requirements.txt exists
            requirements_file = current_dir / "requirements.txt"
            if requirements_file.exists():
                venv_pip = process_dir / "venv/bin/pip"
                pip_install = subprocess.run(
                    f"{venv_pip} install -r {requirements_file}",
                    shell=True,
                    capture_output=True,
                    text=True
                )
                
                if pip_install.returncode != 0:
                    raise PM2CommandError(f"Dependencies installation failed: {pip_install.stderr}")

            # Start/restart the process with config
            start_cmd = f"pm2 start {config_path} --force"
            start_result = subprocess.run(
                start_cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            
            if start_result.returncode != 0:
                raise PM2CommandError(f"Process start failed: {start_result.stderr}")

            # Save PM2 process list
            save_result = subprocess.run(
                "pm2 save",
                shell=True,
                capture_output=True,
                text=True
            )
            
            if save_result.returncode != 0:
                self.logger.warning(f"PM2 save failed: {save_result.stderr}")

            self.logger.info(f"Process {name} updated successfully")
            return {
                "success": True,
                "message": f"Process {name} updated successfully",
                "process_name": name,
                "update_output": git_pull.stdout if 'git_pull' in locals() else "",
                "start_output": start_result.stdout,
                "save_output": save_result.stdout
            }
            
        except Exception as e:
            self.logger.error(f"Failed to update process {name}: {str(e)}", exc_info=True)
            raise

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
    
      
   
    