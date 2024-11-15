# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
import json
import fcntl
from pathlib import Path
from typing import Dict, Optional, Tuple
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
        
    def _run_detached_command(self, cmd: str, log_prefix: str) -> bool:
        """Run command with output redirection to avoid blocking"""
        log_file = Path(f"/tmp/{self.name}_{log_prefix}.log")
        error_file = Path(f"/tmp/{self.name}_{log_prefix}.error")
        done_file = Path(f"/tmp/{self.name}_{log_prefix}.done")
        
        # Clean up any existing files
        for file in [log_file, error_file, done_file]:
            if file.exists():
                file.unlink()
                
        # Run command in background with output redirection
        full_cmd = f"{cmd} > {log_file} 2> {error_file}; echo $? > {done_file}"
        subprocess.Popen(full_cmd, shell=True, preexec_fn=os.setsid)
        
        start_time = time.time()
        while time.time() - start_time < 300:  # 5 minute timeout
            # Check if command completed
            if done_file.exists():
                exit_code = int(done_file.read_text().strip())
                
                # Log output
                if log_file.exists():
                    log_content = log_file.read_text()
                    for line in log_content.splitlines():
                        self.logger.info(f"[{log_prefix}] {line}")
                        
                # Log errors
                if error_file.exists():
                    error_content = error_file.read_text()
                    for line in error_content.splitlines():
                        self.logger.error(f"[{log_prefix} Error] {line}")
                
                # Clean up
                for file in [log_file, error_file, done_file]:
                    if file.exists():
                        file.unlink()
                        
                return exit_code == 0
                
            time.sleep(0.1)  # Short sleep to avoid CPU spinning
            
        # Timeout occurred
        self.logger.error(f"{log_prefix} timed out after 300 seconds")
        return False

    def run(self):
        """Execute deployment process"""
        try:
            # Create directories
            base_path = Path("/home/pm2")
            config_dir = base_path / "pm2-configs"
            process_dir = base_path / "pm2-processes" / self.name
            logs_dir = process_dir / "logs"

            for directory in [config_dir, process_dir, logs_dir]:
                directory.mkdir(parents=True, exist_ok=True)

            # Create config file
            config_path = self.pm2_service.config_generator.generate_config(
                name=self.name,
                repo_url=self.config_data['repository']['url'],
                script=self.config_data.get('script', 'app.py'),
                cron=self.config_data.get('cron'),
                auto_restart=self.config_data.get('auto_restart', True),
                env_vars=self.config_data.get('env_vars')
            )

            # Run setup
            if not self._run_detached_command(
                f"pm2 deploy {config_path} production setup --force",
                "setup"
            ):
                raise PM2CommandError("Setup failed")

            # Run deploy
            if not self._run_detached_command(
                f"pm2 deploy {config_path} production --force",
                "deploy"
            ):
                raise PM2CommandError("Deploy failed")

            # Verify deployment
            verify_cmd = f"pm2 jlist"
            verify_result = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True)
            if verify_result.returncode != 0:
                raise PM2CommandError("Failed to verify process status")
                
            try:
                processes = json.loads(verify_result.stdout)
                process = next((p for p in processes if p['name'] == self.name), None)
                if not process:
                    raise PM2CommandError(f"Process {self.name} not found after deployment")
            except json.JSONDecodeError:
                raise PM2CommandError("Failed to parse process list")

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

    def _cleanup(self):
        """Clean up resources"""
        try:
            # Clean up temp files
            for file in Path("/tmp").glob(f"{self.name}_*"):
                file.unlink()
                
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