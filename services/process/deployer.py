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
                
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=dict(os.environ, PM2_SILENT='true'),
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )

                stdout_data = []
                stderr_data = []

                def log_output():
                    while True:
                        stdout_line = process.stdout.readline()
                        if stdout_line:
                            line = stdout_line.rstrip()
                            self.logger.info(f"[Command Output] {line}")
                            stdout_data.append(stdout_line)
                            
                        stderr_line = process.stderr.readline()
                        if stderr_line:
                            line = stderr_line.rstrip()
                            self.logger.error(f"[Command Error] {line}")
                            stderr_data.append(stderr_line)
                            
                        if not stdout_line and not stderr_line and process.poll() is not None:
                            break

                output_thread = Thread(target=log_output)
                output_thread.daemon = True
                output_thread.start()

                try:
                    process.wait(timeout=timeout)
                    output_thread.join(timeout=1)

                    if process.returncode == 0:
                        output = ''.join(stdout_data)
                        self.logger.info(f"Command completed successfully")
                        return {
                            "success": True,
                            "output": output
                        }
                    else:
                        last_error = ''.join(stderr_data) or ''.join(stdout_data) or str(process.returncode)
                        self.logger.error(f"Command failed with return code {process.returncode}")

                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    last_error = f"Command timed out after {timeout} seconds"
                    self.logger.error(last_error)

                if attempt < max_retries - 1:
                    self.logger.info(f"Retrying in 5 seconds...")
                    time.sleep(5)
                    
            except Exception as e:
                last_error = str(e)
                self.logger.error(f"Unexpected error (attempt {attempt + 1}/{max_retries}): {last_error}")
                if attempt < max_retries - 1:
                    self.logger.info(f"Retrying in 5 seconds...")
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