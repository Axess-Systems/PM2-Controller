# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict, Optional
from threading import Thread
from multiprocessing import Process, Queue
from queue import Empty
from core.config import Config
from core.exceptions import PM2CommandError
from services.pm2.service import PM2Service

class ProcessDeployer(Process):
    def __init__(self, config: Config, name: str, config_data: Dict, result_queue: Queue, logger: logging.Logger):
        super().__init__()
        self.config = config
        self.name = name
        self.config_data = config_data
        self.result_queue = result_queue
        self.logger = logger
        self.pm2_service = PM2Service(config, logger)

    def run(self):
        """Execute deployment process"""
        try:
            # Create deployment script
            deployment_script = self._create_deployment_script()
            
            # Ensure base directories exist
            base_path = Path("/home/pm2")
            config_dir = base_path / "pm2-configs"
            process_dir = base_path / "pm2-processes" / self.name
            logs_dir = process_dir / "logs"

            config_dir.mkdir(parents=True, exist_ok=True)
            process_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)

            # Create config file
            config_path = self.pm2_service.config_generator.generate_config(
                name=self.name,
                repo_url=self.config_data['repository']['url'],
                script=self.config_data.get('script', 'app.py'),
                cron=self.config_data.get('cron'),
                auto_restart=self.config_data.get('auto_restart', True),
                env_vars=self.config_data.get('env_vars')
            )

            # Start deployment process
            deploy_name = f"{self.name}_deploy"
            self.logger.info(f"Starting deployment process as {deploy_name}")
            
            setup_cmd = f"pm2 start {deployment_script} --name {deploy_name} --no-autorestart"
            subprocess.run(setup_cmd, shell=True, check=True, capture_output=True, text=True)

            # Monitor deployment
            start_time = time.time()
            timeout = 600  # 10 minutes timeout
            
            while (time.time() - start_time) < timeout:
                try:
                    status = subprocess.run(
                        f"pm2 show {deploy_name}",
                        shell=True,
                        capture_output=True,
                        text=True
                    )
                    
                    # Check process status
                    if "stopped" in status.stdout:
                        # Clean up deployment process
                        subprocess.run(f"pm2 delete {deploy_name}", shell=True, check=False)
                        os.unlink(deployment_script)
                        
                        if self._check_deployment_success():
                            self.logger.info("Deployment completed successfully")
                            self.result_queue.put({
                                "success": True,
                                "message": f"Process {self.name} created and deployed successfully",
                                "config_file": str(config_path)
                            })
                            return
                        else:
                            raise PM2CommandError("Deployment process completed but verification failed")
                    
                    elif "errored" in status.stdout:
                        error_log = self._get_deployment_logs(deploy_name)
                        raise PM2CommandError(f"Deployment failed with errors: {error_log}")
                        
                except subprocess.CalledProcessError as e:
                    self.logger.error(f"Error checking deployment status: {str(e)}")
                
                time.sleep(5)  # Check every 5 seconds
            
            # Timeout reached
            raise PM2CommandError(f"Deployment timed out after {timeout} seconds")

        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}")
            self._cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e)
            })

    def _create_deployment_script(self) -> str:
        """Create a bash script to handle the deployment"""
        script_path = Path(f"/home/pm2/pm2-configs/{self.name}_deploy.sh")
        
        script_content = f"""#!/bin/bash
set -e

# Log function
log() {{
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}}

log "Starting deployment for {self.name}"

# Ensure directories exist
mkdir -p /home/pm2/pm2-configs
mkdir -p /home/pm2/pm2-processes/{self.name}/logs

# Run setup
log "Running setup"
pm2 deploy /home/pm2/pm2-configs/{self.name}.config.js production setup --force

# Small delay
sleep 2

# Run deploy
log "Running deploy"
pm2 deploy /home/pm2/pm2-configs/{self.name}.config.js production --force

log "Deployment completed"
"""
        
        script_path.write_text(script_content)
        script_path.chmod(0o755)  # Make executable
        
        return str(script_path)

    def _check_deployment_success(self) -> bool:
        """Check if deployment was successful"""
        try:
            # Check if process exists in PM2
            result = subprocess.run(
                f"pm2 show {self.name}",
                shell=True,
                capture_output=True,
                text=True
            )
            
            # Check if process files exist
            config_exists = Path(f"/home/pm2/pm2-configs/{self.name}.config.js").exists()
            process_dir_exists = Path(f"/home/pm2/pm2-processes/{self.name}").exists()
            
            return all([
                result.returncode == 0,
                config_exists,
                process_dir_exists,
                "online" in result.stdout or "stopped" in result.stdout
            ])
        except Exception as e:
            self.logger.error(f"Error checking deployment: {str(e)}")
            return False

    def _get_deployment_logs(self, deploy_name: str) -> str:
        """Get logs from the deployment process"""
        try:
            result = subprocess.run(
                f"pm2 logs {deploy_name} --nostream --lines 50",
                shell=True,
                capture_output=True,
                text=True
            )
            return result.stdout
        except Exception as e:
            return f"Error getting deployment logs: {str(e)}"

    def _cleanup(self):
        """Clean up resources on failure"""
        try:
            # Clean up deployment process if it exists
            deploy_name = f"{self.name}_deploy"
            subprocess.run(f"pm2 delete {deploy_name}", shell=True, check=False)
            
            # Clean up deployment script
            deploy_script = Path(f"/home/pm2/pm2-configs/{self.name}_deploy.sh")
            if deploy_script.exists():
                deploy_script.unlink()

            # Clean up process files
            for path in [
                Path(f"/home/pm2/pm2-configs/{self.name}.config.js"),
                Path(f"/home/pm2/pm2-processes/{self.name}")
            ]:
                if path.exists():
                    if path.is_file():
                        path.unlink()
                    else:
                        shutil.rmtree(path)
        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}")