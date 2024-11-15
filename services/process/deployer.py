# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict
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
            # Ensure directories exist first
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

            # Run setup with retries
            setup_result = self._run_command(
                f"pm2 deploy {config_path} production setup --force",
                timeout=300
            )
            if not setup_result["success"]:
                raise PM2CommandError(f"Setup failed: {setup_result['error']}")

            # Small delay between setup and deploy
            time.sleep(2)

            # Run deploy with retries
            deploy_result = self._run_command(
                f"pm2 deploy {config_path} production --force",
                timeout=300
            )
            if not deploy_result["success"]:
                raise PM2CommandError(f"Deploy failed: {deploy_result['error']}")

            self.result_queue.put({
                "success": True,
                "message": f"Process {self.name} created and deployed successfully",
                "config_file": str(config_path),
                "setup_output": setup_result["output"],
                "deploy_output": deploy_result["output"]
            })

        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}")
            self._cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e)
            })

    def _run_command(self, cmd: str, timeout: int = 300, max_retries: int = 3) -> Dict:
        """Execute command with retries and timeout"""
        last_error = None
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Running command (attempt {attempt + 1}/{max_retries}): {cmd}")
                result = subprocess.run(
                    cmd,
                    shell=True,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=dict(os.environ, PM2_SILENT='true')
                )
                return {
                    "success": True,
                    "output": result.stdout.strip()
                }

            except subprocess.TimeoutExpired as e:
                last_error = f"Command timed out after {timeout} seconds"
                self.logger.error(f"Command timeout (attempt {attempt + 1}/{max_retries})")

            except subprocess.CalledProcessError as e:
                last_error = e.stderr.strip() or e.stdout.strip() or str(e)
                self.logger.error(f"Command failed (attempt {attempt + 1}/{max_retries}): {last_error}")

            except Exception as e:
                last_error = str(e)
                self.logger.error(f"Unexpected error (attempt {attempt + 1}/{max_retries}): {last_error}")

            if attempt < max_retries - 1:
                time.sleep(5)

        return {
            "success": False,
            "error": last_error or "Command failed after all retries"
        }

    def _cleanup(self):
        """Clean up resources on failure"""
        try:
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