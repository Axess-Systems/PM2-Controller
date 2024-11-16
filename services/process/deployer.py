import os
import time
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict
from multiprocessing import Process, Queue
from core.config import Config
from core.exceptions import PM2CommandError
from services.pm2.service import PM2Service
import select

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
            base_path = Path("/home/pm2")
            config_dir = base_path / "pm2-configs"
            process_dir = base_path / "pm2-processes" / self.name
            logs_dir = process_dir / "logs"

            config_dir.mkdir(parents=True, exist_ok=True)
            process_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)

            config_path = self.pm2_service.config_generator.generate_config(
                name=self.name,
                repo_url=self.config_data['repository']['url'],
                script=self.config_data.get('script', 'main.py'),
                cron=self.config_data.get('cron'),
                auto_restart=self.config_data.get('auto_restart', True),
                env_vars=self.config_data.get('env_vars')
            )

            setup_result = self.run_command(
                f"pm2 deploy {config_path} production setup --force",
                "Setup",
                timeout=60
            )

            if not setup_result.get('success'):
                raise PM2CommandError(f"Setup failed: {setup_result.get('error')}")

            deploy_result = self.run_command(
                f"pm2 deploy {config_path} production --force",
                "Deploy",
                timeout=60
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

    def read_nonblocking(self, stream):
        """Read non-blocking from a subprocess stream."""
        outputs = []
        while True:
            ready, _, _ = select.select([stream], [], [], 0.1)
            if stream in ready:
                line = stream.readline()
                if line:
                    outputs.append(line.strip())
                else:
                    break
        return outputs

    def run_command(self, cmd: str, label: str, timeout: int = 60) -> Dict:
        """Run command with timeout and non-blocking I/O."""
        try:
            process = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            start_time = time.time()
            stdout_lines, stderr_lines = [], []

            while True:
                if time.time() - start_time > timeout:
                    process.terminate()
                    return {"success": False, "error": f"Timeout after {timeout} seconds"}

                stdout_lines.extend(self.read_nonblocking(process.stdout))
                stderr_lines.extend(self.read_nonblocking(process.stderr))

                if process.poll() is not None:
                    break

                time.sleep(0.1)

            success = process.returncode == 0
            for line in stdout_lines:
                self.logger.info(f"[{label}] {line}")
            for line in stderr_lines:
                self.logger.error(f"[{label} Error] {line}")

            return {"success": success, "error": stderr_lines[-1] if not success else None}

        except Exception as e:
            self.logger.error(f"Command execution failed: {str(e)}")
            return {"success": False, "error": str(e)}

    def cleanup(self):
        """Clean up resources on failure"""
        try:
            subprocess.run(f"pm2 delete {self.name}", shell=True, check=False)
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
