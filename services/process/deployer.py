# services/process/deployer.py
import os
import time
import shutil
import logging
import asyncio
import signal
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
        self._process = None

    def run(self):
        """Execute deployment process"""
        try:
            # Set up signal handlers
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)

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
            setup_result = asyncio.run(self._run_command_async(
                f"pm2 deploy {config_path} production setup --force",
                timeout=300
            ))
            if not setup_result["success"]:
                raise PM2CommandError(f"Setup failed: {setup_result['error']}")

            # Small delay between setup and deploy
            time.sleep(2)

            # Run deploy with retries
            deploy_result = asyncio.run(self._run_command_async(
                f"pm2 deploy {config_path} production --force",
                timeout=300
            ))
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

    async def _run_command_async(self, cmd: str, timeout: int = 300, max_retries: int = 3) -> Dict:
        """Execute command with retries and timeout using asyncio"""
        last_error = None
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Running command (attempt {attempt + 1}/{max_retries}): {cmd}")
                
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=dict(os.environ, PM2_SILENT='true')
                )
                
                self._process = process
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )
                    
                    if process.returncode == 0:
                        return {
                            "success": True,
                            "output": stdout.decode().strip()
                        }
                    else:
                        last_error = stderr.decode().strip() or stdout.decode().strip()
                        self.logger.error(f"Command failed (attempt {attempt + 1}/{max_retries}): {last_error}")
                
                except asyncio.TimeoutError:
                    if process.returncode is None:
                        process.terminate()
                        await process.wait()
                    last_error = f"Command timed out after {timeout} seconds"
                    self.logger.error(f"Command timeout (attempt {attempt + 1}/{max_retries})")

            except Exception as e:
                last_error = str(e)
                self.logger.error(f"Unexpected error (attempt {attempt + 1}/{max_retries}): {last_error}")

            if attempt < max_retries - 1:
                await asyncio.sleep(5)

        return {
            "success": False,
            "error": last_error or "Command failed after all retries"
        }

    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        self.logger.info(f"Received signal {signum}, cleaning up...")
        if self._process and self._process.returncode is None:
            self._process.terminate()
        self._cleanup()
        self.result_queue.put({
            "success": False,
            "message": f"Process {self.name} deployment interrupted",
            "error": "Deployment interrupted by signal"
        })
        os._exit(1)

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