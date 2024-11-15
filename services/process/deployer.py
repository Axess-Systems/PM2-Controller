# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
import json
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

            # Execute setup in background
            setup_proc = subprocess.Popen(
                f"pm2 deploy {config_path} production setup --force",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,  # Run in new process group
                universal_newlines=True
            )

            # Monitor setup process
            while True:
                return_code = setup_proc.poll()
                
                # Process stdout/stderr
                if setup_proc.stdout:
                    line = setup_proc.stdout.readline()
                    if line:
                        self.logger.info(f"[Setup] {line.strip()}")
                if setup_proc.stderr:
                    line = setup_proc.stderr.readline()
                    if line:
                        self.logger.error(f"[Setup Error] {line.strip()}")

                if return_code is not None:
                    if return_code != 0:
                        raise PM2CommandError("Setup failed")
                    break

            # Execute deploy in background
            deploy_proc = subprocess.Popen(
                f"pm2 deploy {config_path} production --force",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,
                universal_newlines=True
            )

            # Monitor deploy process
            while True:
                return_code = deploy_proc.poll()
                
                # Process stdout/stderr
                if deploy_proc.stdout:
                    line = deploy_proc.stdout.readline()
                    if line:
                        self.logger.info(f"[Deploy] {line.strip()}")
                if deploy_proc.stderr:
                    line = deploy_proc.stderr.readline()
                    if line:
                        self.logger.error(f"[Deploy Error] {line.strip()}")

                if return_code is not None:
                    if return_code != 0:
                        raise PM2CommandError("Deploy failed")
                    break

            # Verify process is running
            verify_cmd = f"pm2 jlist"
            verify_result = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True)
            
            if verify_result.returncode != 0:
                raise PM2CommandError("Failed to verify process status")
                
            processes = json.loads(verify_result.stdout)
            process = next((p for p in processes if p['name'] == self.name), None)
            
            if not process:
                raise PM2CommandError(f"Process {self.name} not found after deployment")

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