# services/process/deployer.py
from multiprocessing import Process, Queue
from queue import Empty
from typing import Dict
import logging
import time
import subprocess
from pathlib import Path
import shutil
import os
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
       try:
           # Ensure directories exist
           Path("/home/pm2/pm2-configs").mkdir(parents=True, exist_ok=True)
           base_dir = Path(f"/home/pm2/pm2-processes/{self.name}")
           base_dir.mkdir(parents=True, exist_ok=True)
           (base_dir / "logs").mkdir(parents=True, exist_ok=True)
           
           # Create config
           config_path = self.pm2_service.config_generator.generate_config(
               name=self.name,
               repo_url=self.config_data['repository']['url'],
               script=self.config_data.get('script', 'app.py'),
               cron=self.config_data.get('cron'),
               auto_restart=self.config_data.get('auto_restart', True),
               env_vars=self.config_data.get('env_vars')
           )

           # Verify config exists
           if not config_path.exists():
               raise PM2CommandError(f"Failed to create config file at {config_path}")

           # Setup with retries
           setup_cmd = f"pm2 deploy {config_path} production setup --force"
           setup_result = self._run_command_with_retry(setup_cmd)
           if not setup_result["success"]:
               raise PM2CommandError(f"Setup failed: {setup_result.get('error')}")

           time.sleep(2)

           # Deploy with retries
           deploy_cmd = f"pm2 deploy {config_path} production --force"
           deploy_result = self._run_command_with_retry(deploy_cmd)
           if not deploy_result["success"]:
               raise PM2CommandError(f"Deploy failed: {deploy_result.get('error')}")

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

   def _run_command_with_retry(self, cmd: str, max_retries: int = 3) -> Dict:
       """Run command with retries and proper output capture"""
       for attempt in range(max_retries):
           try:
               self.logger.info(f"Running command (attempt {attempt + 1}/{max_retries}): {cmd}")
               result = subprocess.run(
                   cmd,
                   shell=True,
                   check=True,
                   capture_output=True,
                   text=True,
                   env=dict(os.environ, PM2_SILENT='true')
               )
               return {"success": True, "output": result.stdout}
           except subprocess.CalledProcessError as e:
               error = e.stderr or e.stdout or str(e)
               self.logger.error(f"Command failed (attempt {attempt + 1}/{max_retries}): {error}")
               if attempt < max_retries - 1:
                   time.sleep(5)
               else:
                   return {"success": False, "error": error}
       return {"success": False, "error": "Max retries reached"}

   def _cleanup(self):
       """Clean up resources on failure"""
       try:
           paths = [
               Path(f"/home/pm2/pm2-configs/{self.name}.config.js"),
               Path(f"/home/pm2/pm2-processes/{self.name}")
           ]
           for path in paths:
               if path.exists():
                   if path.is_file():
                       path.unlink()
                   else:
                       shutil.rmtree(path)
       except Exception as e:
           self.logger.error(f"Cleanup failed: {str(e)}")