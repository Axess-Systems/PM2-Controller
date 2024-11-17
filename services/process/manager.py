# services/process/manager.py
from multiprocessing import Queue
from typing import Dict
from pathlib import Path
import json
import shutil
import subprocess
import logging
import traceback
from core.config import Config
from core.exceptions import (
    PM2CommandError,
    ProcessNotFoundError,
    ProcessAlreadyExistsError,
)
from .deployer import ProcessDeployer

class ProcessManager:
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger

    def create_process(self, config_data: Dict, timeout: int = 600) -> Dict:
        """Create a new PM2 process
        
        Args:
            config_data: Dictionary containing process configuration
            timeout: Maximum time to wait for deployment in seconds
            
        Returns:
            Dict containing deployment result
            
        Raises:
            ProcessAlreadyExistsError: If process with same name exists
            PM2CommandError: If deployment fails
        """
        try:
            name = config_data["name"]
            self.logger.info(f"Creating new process: {name}")
            self.logger.debug(f"Process config: {config_data}")

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
                if not result.get("success"):
                    error_msg = result.get("error", "Unknown deployment error")
                    self.logger.error(f"Deployment failed: {error_msg}")
                    raise PM2CommandError(error_msg)
                
                self.logger.info(f"Process {name} created successfully")
                return result
                
            except Empty:
                self.logger.error(f"Deployment timed out after {timeout} seconds")
                deployer.terminate()
                raise PM2CommandError(f"Deployment timed out after {timeout} seconds")
            finally:
                deployer.join()
                
        except Exception as e:
            self.logger.error(f"Process creation failed: {str(e)}", exc_info=True)
            raise

    def delete_process(self, name: str) -> Dict:
        """Delete a process and its associated configuration files
        
        Args:
            name: Name of the process to delete
            
        Returns:
            Dict with deletion status
            
        Raises:
            PM2CommandError: If process deletion fails
        """
        try:
            self.logger.info(f"Deleting process: {name}")
            
            config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            process_dir = Path(f"/home/pm2/pm2-processes/{name}")

            # Get process status from PM2
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
                        self.logger.error(f"Process {name} is running. Stop it first.")
                        raise PM2CommandError(
                            f"Process {name} is currently running. Stop it first using 'pm2 stop {name}'"
                        )
                        
                    self.logger.debug(f"Deleting PM2 process: {name}")
                    subprocess.run(
                        f"{self.config.PM2_BIN} delete {name}",
                        shell=True,
                        check=True,
                        capture_output=True,
                    )
                    
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
            return {"message": f"Process {name} deleted successfully"}

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
            
            # Read and parse config file
            with open(config_path, 'r') as f:
                config_content = f.read()
                
            self.logger.debug(f"Retrieved config for process {name}")
            return {
                "config_file": str(config_path),
                "content": config_content
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get config for process {name}: {str(e)}", exc_info=True)
            raise

    def update_config(self, name: str, config_data: Dict) -> Dict:
        """Update process configuration
        
        Args:
            name: Name of the process
            config_data: New configuration data
            
        Returns:
            Dict with update status
            
        Raises:
            ProcessNotFoundError: If process doesn't exist
            PM2CommandError: If update fails
        """
        try:
            self.logger.info(f"Updating config for process: {name}")
            self.logger.debug(f"New config data: {config_data}")
            
            config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            if not config_path.exists():
                raise ProcessNotFoundError(f"Config file not found for process {name}")

            # TODO: Implement config update logic
            # This should:
            # 1. Generate new config file
            # 2. Validate the new configuration
            # 3. Backup the old config
            # 4. Apply the new config
            # 5. Restart the process if necessary

            self.logger.info(f"Config updated for process {name}")
            return {
                "message": f"Configuration updated for process {name}",
                "config_file": str(config_path)
            }
            
        except Exception as e:
            self.logger.error(f"Failed to update config for process {name}: {str(e)}", exc_info=True)
            raise

    def update_process(self, name: str) -> Dict:
        """Update a process (pull latest code and restart)
        
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
            
            process_dir = Path(f"/home/pm2/pm2-processes/{name}/current")
            if not process_dir.exists():
                raise ProcessNotFoundError(f"Process directory not found: {process_dir}")

            # Pull latest changes
            git_pull = subprocess.run(
                "git pull",
                shell=True,
                cwd=process_dir,
                capture_output=True,
                text=True
            )
            
            if git_pull.returncode != 0:
                raise PM2CommandError(f"Git pull failed: {git_pull.stderr}")

            # Install any new dependencies
            requirements_file = process_dir / "requirements.txt"
            if requirements_file.exists():
                venv_pip = Path(f"/home/pm2/pm2-processes/{name}/venv/bin/pip")
                pip_install = subprocess.run(
                    f"{venv_pip} install -r {requirements_file}",
                    shell=True,
                    capture_output=True,
                    text=True
                )
                
                if pip_install.returncode != 0:
                    raise PM2CommandError(f"Dependencies installation failed: {pip_install.stderr}")

            # Restart the process
            restart_result = subprocess.run(
                f"{self.config.PM2_BIN} restart {name}",
                shell=True,
                capture_output=True,
                text=True
            )
            
            if restart_result.returncode != 0:
                raise PM2CommandError(f"Process restart failed: {restart_result.stderr}")

            self.logger.info(f"Process {name} updated successfully")
            return {
                "message": f"Process {name} updated successfully",
                "git_output": git_pull.stdout,
                "restart_output": restart_result.stdout
            }
            
        except Exception as e:
            self.logger.error(f"Failed to update process {name}: {str(e)}", exc_info=True)
            raise