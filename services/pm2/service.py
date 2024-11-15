# services/pm2/service.py
import time
import json
import subprocess
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
    
    def list_processes(self) -> List[Dict]:
        """Get list of all PM2 processes with enhanced information"""
        processes = self.commands.execute("jlist")
        
        for process in processes:
            try:
                pm2_config = Path(f"/home/pm2/pm2-configs/{process['name']}.config.js")
                python_config = Path(f"/home/pm2/pm2-configs/{process['name']}.ini")
                
                process['config_files'] = {
                    'pm2_config': str(pm2_config) if pm2_config.exists() else None,
                    'python_config': str(python_config) if python_config.exists() else None
                }
            except Exception as e:
                self.logger.warning(f"Error getting config paths for {process['name']}: {str(e)}")
        
        return processes

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

