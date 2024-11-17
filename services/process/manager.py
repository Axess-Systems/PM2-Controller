# services/process/manager.py
from multiprocessing import Queue
from typing import Dict, Optional
from pathlib import Path
import json
import shutil
import subprocess
import logging
import re
from datetime import datetime

from queue import Empty
from core.config import Config
from core.exceptions import (
    PM2CommandError,
    ProcessNotFoundError,
    ProcessAlreadyExistsError,
)
from .deployer import ProcessDeployer
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

    def create_process(self, config_data: Dict, timeout: int = 600) -> Dict:
        """Create a new PM2 process
        
        Args:
            config_data: Dictionary containing process configuration
            timeout: Maximum time to wait for deployment in seconds
            
        Returns:
            Dict with deployment result
            
        Raises:
            ProcessAlreadyExistsError: If process already exists
            PM2CommandError: If deployment fails
        """
        try:
            name = config_data["name"]
            self.logger.info(f"Creating new process: {name}")
            self.logger.debug(f"Process configuration: {json.dumps(config_data, indent=2)}")

            config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            if config_path.exists():
                raise ProcessAlreadyExistsError(f"Process {name} already exists")

            result_queue = Queue()
            deployer = ProcessDeployer(
                config=self.config,
                name=name,
                config_data=config_data,
                result_queue=result_queue,
                logger=self.logger,
            )

            self.logger.debug("Starting deployment process")
            deployer.start()

            try:
                result = result_queue.get(timeout=timeout)
                if not result:
                    raise PM2CommandError("Deployment failed: No result received")
                    
                if not result.get("success", False):
                    error_msg = result.get("error") or result.get("message") or "Unknown deployment error"
                    self.logger.error(f"Deployment failed: {error_msg}")
                    raise PM2CommandError(error_msg)
                
                self.logger.info(f"Process {name} created successfully")
                return {
                    "success": True,
                    "message": f"Process {name} created successfully",
                    "process_name": name,
                    "config_file": result.get("config_file"),
                    "details": result.get("details", {})
                }
                
            except Empty:
                self.logger.error(f"Deployment timed out after {timeout} seconds")
                deployer.terminate()
                raise PM2CommandError(f"Deployment timed out after {timeout} seconds")
            finally:
                deployer.join()
                
        except (ProcessAlreadyExistsError, PM2CommandError):
            raise
        except Exception as e:
            self.logger.error(f"Process creation failed: {str(e)}", exc_info=True)
            raise PM2CommandError(f"Process creation failed: {str(e)}")

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
        """Update process code and restart
        
        Args:
            name: Name of the process
            
        Returns:
            Dict with update status
            
        Raises:
            ProcessNotFoundError: If process doesn't exist
            PM2CommandError: If update fails
        """
        try:
            self.logger.info(f"Updating process: {name}")
            
            config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            process_dir = Path(f"/home/pm2/pm2-processes/{name}/current")
            
            if not config_path.exists():
                raise ProcessNotFoundError(f"Config file not found for {name}")
            
            if not process_dir.exists():
                raise ProcessNotFoundError(f"Process directory not found: {process_dir}")

            # Run PM2 deploy update command
            deploy_cmd = f"pm2 deploy {config_path} production update --force"
            deploy_result = subprocess.run(
                deploy_cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            
            if deploy_result.returncode != 0:
                raise PM2CommandError(f"Deploy update failed: {deploy_result.stderr}")

            # Start the process with updated config
            start_cmd = f"pm2 start {config_path}"
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
                "deploy_output": deploy_result.stdout,
                "start_output": start_result.stdout,
                "save_output": save_result.stdout
            }
            
        except Exception as e:
            self.logger.error(f"Failed to update process {name}: {str(e)}", exc_info=True)
            raise

    def update_config(self, name: str, config_data: Dict) -> Dict:
        """Update process configuration
        
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

            # Check if process exists
            config_file = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            if not config_file.exists():
                raise ProcessNotFoundError(f"Config file not found for {name}")

            # Read current config
            current_config = self.get_process_config(name)

            # Generate updated config file
            backup_file = config_file.with_suffix('.backup')
            shutil.copy2(config_file, backup_file)

            try:
                # Update the config file
                with open(config_file, 'w') as f:
                    f.write(self._update_config_content(current_config['content'], config_data))

                # Reload the process with new config
                reload_result = subprocess.run(
                    f"pm2 reload {name}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=True
                )

                return {
                    "success": True,
                    "message": f"Configuration updated for process {name}",
                    "config_file": str(config_file),
                    "reload_output": reload_result.stdout
                }

            except Exception as e:
                # Restore backup on failure
                if backup_file.exists():
                    shutil.copy2(backup_file, config_file)
                raise e

            finally:
                # Clean up backup
                if backup_file.exists():
                    backup_file.unlink()

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to reload process: {e.stderr}")
            raise PM2CommandError(f"Failed to reload process: {e.stderr}")
        except Exception as e:
            self.logger.error(f"Failed to update config for {name}: {str(e)}")
            raise PM2CommandError(f"Config update failed: {str(e)}")

    def _update_config_content(self, current_content: str, new_config: Dict) -> str:
        """Update config file content with new values
        
        Args:
            current_content: Current config file content
            new_config: New configuration values
            
        Returns:
            Updated config file content
        """
        content = current_content

        # Update basic fields
        if 'script' in new_config:
            content = re.sub(
                r'script:\s*[\'"].*?[\'"]',
                f'script: "{new_config["script"]}"',
                content
            )

        if 'cron' in new_config:
            if new_config['cron']:
                if 'cron_restart' not in content:
                    content = content.replace(
                        'watch: false,',
                        f'watch: false,\n        cron_restart: "{new_config["cron"]},"'
                    )
                else:
                    content = re.sub(
                        r'cron_restart:\s*[\'"].*?[\'"]',
                        f'cron_restart: "{new_config["cron"]}"',
                        content
                    )
            else:
                content = re.sub(r',?\s*cron_restart:\s*[\'"].*?[\'"]', '', content)

        if 'auto_restart' in new_config:
            content = re.sub(
                r'autorestart:\s*\w+',
                f'autorestart: {str(new_config["auto_restart"]).lower()}',
                content
            )

        # Update environment variables
        if 'env_vars' in new_config and new_config['env_vars']:
            env_vars = new_config['env_vars']
            env_block = '    env: {\n'
            for key, value in env_vars.items():
                env_block += f'        {key}: "{value}",\n'
            env_block += '    },'

            if 'env:' in content:
                content = re.sub(
                    r'env:\s*{[^}]*}',
                    env_block.strip(),
                    content,
                    flags=re.DOTALL
                )
            else:
                content = content.replace(
                    'watch: false,',
                    f'watch: false,\n{env_block}'
                )

        return content