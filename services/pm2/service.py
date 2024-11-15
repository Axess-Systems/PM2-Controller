# services/pm2/service.py
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional
from collections import deque
from core.config import Config
from core.exceptions import ProcessNotFoundError
from .commands import PM2Commands
from .config import PM2Config

class PM2Service:
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.commands = PM2Commands(config, logger)
        self.config_generator = PM2Config(logger)
       
    def run_pm2_deploy_command(self, process_name: str, command: str = "") -> Dict:
        config_path = f"/home/pm2/pm2-configs/{process_name}.config.js"
        cmd = f"pm2 deploy {config_path} production"
        if command:
            cmd += f" {command}"
        cmd += " --force"
       
        for attempt in range(3):
            result = self.commands.execute(cmd)
            if result["success"]:
                return result
            if attempt < 2:
                self.logger.warning(f"Retrying command... ({attempt + 1}/3)")
                time.sleep(5)
        return result

    def get_process(self, name: str) -> Dict:
        """Get details of a specific process"""
        processes = self.list_processes()
        process = next((p for p in processes if p['name'] == name), None)
        
        if not process:
            raise ProcessNotFoundError(f"Process {name} not found")
        
        return process

    def start_process(self, name: str) -> str:
        """Start a process"""
        process = self.get_process(name)
        return self.commands.execute(f"start {process['pm_id']}")
    
    def stop_process(self, name: str) -> str:
        """Stop a process"""
        process = self.get_process(name)
        return self.commands.execute(f"stop {process['pm_id']}")
    
    def restart_process(self, name: str) -> str:
        """Restart a process"""
        process = self.get_process(name)
        return self.commands.execute(f"restart {process['pm_id']}")

