# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
import json
import asyncio
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
            # Create new event loop for this process
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run deployment
            loop.run_until_complete(self._deploy())
            
        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}")
            self._cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e)
            })
        finally:
            loop.close()

    async def _deploy(self):
        """Async deployment process"""
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

        # Run setup
        self.logger.info(f"Running setup for {self.name}")
        setup_success = await self._run_command(
            f"pm2 deploy {config_path} production setup --force",
            "Setup"
        )
        if not setup_success:
            raise PM2CommandError("Setup failed")

        # Run deploy
        self.logger.info(f"Running deploy for {self.name}")
        deploy_success = await self._run_command(
            f"pm2 deploy {config_path} production --force",
            "Deploy"
        )
        if not deploy_success:
            raise PM2CommandError("Deploy failed")

        # Verify deployment
        self.logger.info("Verifying deployment")
        success = await self._verify_deployment()
        if not success:
            raise PM2CommandError("Deployment verification failed")

        self.result_queue.put({
            "success": True,
            "message": f"Process {self.name} created and deployed successfully",
            "config_file": str(config_path)
        })

    async def _run_command(self, cmd: str, label: str) -> bool:
        """Run command asynchronously with output capture"""
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        async def read_stream(stream, is_error):
            while True:
                line = await stream.readline()
                if not line:
                    break
                line = line.decode().strip()
                if line:
                    if is_error:
                        self.logger.error(f"[{label} Error] {line}")
                    else:
                        self.logger.info(f"[{label}] {line}")

        # Process stdout and stderr concurrently
        await asyncio.gather(
            read_stream(process.stdout, False),
            read_stream(process.stderr, True)
        )

        # Wait for command to complete
        return await process.wait() == 0

    async def _verify_deployment(self) -> bool:
        """Verify deployment success"""
        try:
            process = await asyncio.create_subprocess_shell(
                f"pm2 jlist",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, _ = await process.communicate()
            
            if process.returncode != 0:
                return False

            processes = json.loads(stdout)
            return any(p['name'] == self.name for p in processes)
            
        except Exception as e:
            self.logger.error(f"Verification failed: {str(e)}")
            return False

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