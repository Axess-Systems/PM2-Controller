# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
import threading
from pathlib import Path
from typing import Dict
from multiprocessing import Process, Queue
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
                script=self.config_data.get('script', 'main.py'),
                cron=self.config_data.get('cron'),
                auto_restart=self.config_data.get('auto_restart', True),
                env_vars=self.config_data.get('env_vars')
            )

            # Run setup and deploy
            setup_result = self.run_command(
                f"pm2 deploy {config_path} production setup --force",
                "Setup"
            )
            
            if not setup_result.get('success'):
                raise PM2CommandError(f"Setup failed: {setup_result.get('error')}")

            deploy_result = self.run_command(
                f"pm2 deploy {config_path} production --force",
                "Deploy"
            )
            
            if not deploy_result.get('success'):
                raise PM2CommandError(f"Deploy failed: {deploy_result.get('error')}")

            self.result_queue.put({
                "success": True,
                "message": f"Process {self.name} created and deployed successfully",
                "config_file": str(config_path)
            })

        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}")
            self.cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e)
            })

    def run_command(self, cmd: str, label: str) -> Dict:
        """Run command and capture output"""
        try:
            self.logger.info(f"Running command: {cmd}")
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300
            )

            # Log output
            for line in result.stdout.splitlines():
                if line.strip():
                    self.logger.info(f"[{label}] {line.strip()}")
            
            # Log errors
            error_detected = False
            error_message = None
            for line in result.stderr.splitlines():
                if line.strip() and "Cloning into" not in line:
                    self.logger.error(f"[{label} Error] {line.strip()}")
                    error_detected = True
                    error_message = line.strip()

            return {
                'success': result.returncode == 0 and not error_detected,
                'error': error_message if error_detected else None
            }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Command timed out after 300 seconds'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def cleanup(self):
        """Clean up resources on failure"""
        try:
            # Stop and delete PM2 process
            subprocess.run(f"pm2 delete {self.name}", shell=True, check=False)

            # Clean up files
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