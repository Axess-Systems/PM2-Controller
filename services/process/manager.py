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
        """Update process configuration by regenerating the config file
        
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
                # Extract repository info from current config
                with open(config_file, 'r') as f:
                    current_content = f.read()
                    repo_match = re.search(r'repo:\s*[\'"](.+?)[\'"]', current_content)
                    branch_match = re.search(r'ref:\s*[\'"](.+?)[\'"]', current_content)
                    
                    if not repo_match:
                        raise PM2CommandError("Could not extract repository URL from current config")
                    
                    repo_url = repo_match.group(1)
                    branch = branch_match.group(1) if branch_match else "main"

                # Generate new config using PM2Config
                new_config = self.pm2_service.generate_config(
                    name=name,
                    repo_url=repo_url,
                    script=config_data.get('script', process.get('pm2_env', {}).get('pm_exec_path', 'app.py')),
                    branch=branch,
                    cron=config_data.get('cron'),
                    auto_restart=config_data.get('auto_restart', True),
                    env_vars=config_data.get('env_vars', {})
                )

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
                    "config_file": str(new_config),
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
    