# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict, Optional
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
            # Create directories
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

            # Create deployment script
            script_path = self._create_deployment_script(config_path)
            
            # Run setup and deploy in background
            deploy_log = process_dir / "deploy.log"
            deploy_cmd = f"nohup bash {script_path} > {deploy_log} 2>&1 &"
            
            # Start deployment
            self.logger.info(f"Starting deployment for {self.name}")
            subprocess.run(deploy_cmd, shell=True, check=True)

            # Monitor deployment log for completion
            start_time = time.time()
            timeout = 600  # 10 minutes
            success = False

            while (time.time() - start_time) < timeout:
                if deploy_log.exists():
                    log_content = deploy_log.read_text()
                    self.logger.info(f"[Deployment Log] {log_content}")
                    
                    if "Deployment completed" in log_content:
                        success = True
                        break
                    elif "Deployment failed" in log_content:
                        break
                
                time.sleep(5)

            if not success:
                raise PM2CommandError(f"Deployment failed or timed out. Check {deploy_log} for details")

            # Verify deployment
            if not self._verify_deployment():
                raise PM2CommandError("Deployment verification failed")

            self.result_queue.put({
                "success": True,
                "message": f"Process {self.name} created and deployed successfully",
                "config_file": str(config_path)
            })

        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}")
            self._cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e)
            })

    def _create_deployment_script(self, config_path: Path) -> Path:
        """Create deployment script"""
        script_path = Path(f"/home/pm2/pm2-configs/{self.name}_deploy.sh")
        
        script_content = f"""#!/bin/bash
set -e

echo "Starting deployment for {self.name} at $(date)"

# Setup phase
echo "Running setup..."
pm2 deploy {config_path} production setup --force
if [ $? -ne 0 ]; then
    echo "Deployment failed during setup"
    exit 1
fi

# Short delay
sleep 2

# Deploy phase
echo "Running deploy..."
pm2 deploy {config_path} production --force
if [ $? -ne 0 ]; then
    echo "Deployment failed during deploy"
    exit 1
fi

echo "Deployment completed successfully at $(date)"
"""
        
        script_path.write_text(script_content)
        script_path.chmod(0o755)
        return script_path

    def _verify_deployment(self) -> bool:
        """Verify deployment success"""
        try:
            result = subprocess.run(
                f"pm2 show {self.name}",
                shell=True,
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"Deployment verification failed: {str(e)}")
            return False

    def _cleanup(self):
        """Clean up resources"""
        try:
            # Clean up script and logs
            script_path = Path(f"/home/pm2/pm2-configs/{self.name}_deploy.sh")
            if script_path.exists():
                script_path.unlink()

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