# services/pm2/service.py
import subprocess
import json
import time
from typing import List, Dict
import logging
from core.config import Config
from core.exceptions import PM2Error, ProcessNotFoundError

class PM2Service:
    """Service for interacting with PM2 process manager with improved error handling"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._verify_pm2_installation()
    
    def _verify_pm2_installation(self):
        """Verify PM2 is installed and accessible"""
        try:
            result = subprocess.run(
                f"{self.config.PM2_BIN} --version",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                self.logger.error(f"PM2 version check failed: {result.stderr}")
                raise PM2Error("PM2 is not properly installed or accessible")
            self.logger.info(f"PM2 version: {result.stdout.strip()}")
        except Exception as e:
            self.logger.error(f"PM2 verification failed: {str(e)}")
            raise PM2Error(f"PM2 verification failed: {str(e)}")
    
    def list_processes(self) -> List[Dict]:
        """Get list of all PM2 processes with improved error handling"""
        try:
            result = subprocess.run(
                f"{self.config.PM2_BIN} jlist",
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.config.COMMAND_TIMEOUT
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Unknown error"
                self.logger.error(f"PM2 list processes failed: {error_msg}")
                raise PM2Error(f"Failed to list processes: {error_msg}")
            
            try:
                processes = json.loads(result.stdout)
                return processes
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to parse PM2 process list: {str(e)}")
                raise PM2Error(f"Invalid PM2 process list format: {str(e)}")
                
        except subprocess.TimeoutExpired:
            error_msg = f"PM2 command timed out after {self.config.COMMAND_TIMEOUT} seconds"
            self.logger.error(error_msg)
            raise PM2Error(error_msg)
            
        except Exception as e:
            self.logger.error(f"Unexpected error listing processes: {str(e)}")
            raise PM2Error(f"Failed to list processes: {str(e)}")
            
    def get_process(self, name: str) -> Dict:
        """Get details of a specific process with improved error handling"""
        try:
            processes = self.list_processes()
            process = next((p for p in processes if p['name'] == name), None)
            
            if not process:
                raise ProcessNotFoundError(f"Process {name} not found")
                
            return process
            
        except ProcessNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Error getting process {name}: {str(e)}")
            raise PM2Error(f"Failed to get process details: {str(e)}")