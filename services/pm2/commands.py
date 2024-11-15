# services/pm2/commands.py

import os
import json
import subprocess
import logging
from typing import Dict
from pathlib import Path
from core.exceptions import PM2CommandError, ProcessNotFoundError

class PM2Commands:
    """Handles PM2 command execution and retry logic"""
    
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger

    def execute(self, command: str, retry: bool = True) -> Dict:
        """Execute a PM2 command with enhanced error handling and retry logic"""
        retries = self.config.MAX_RETRIES if retry else 1
        last_error = None
        
        for attempt in range(retries):
            try:
                result = subprocess.run(
                    f"{self.config.PM2_BIN} {command}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=self.config.COMMAND_TIMEOUT
                )
                
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode, 
                        command, 
                        result.stdout, 
                        result.stderr
                    )
                
                if 'jlist' in command:
                    try:
                        return json.loads(result.stdout)
                    except json.JSONDecodeError as e:
                        raise PM2CommandError(f"Invalid JSON output from PM2: {str(e)}")
                return result.stdout
                
            except subprocess.TimeoutExpired as e:
                last_error = f"Command timed out after {self.config.COMMAND_TIMEOUT} seconds"
                self.logger.error(f"PM2 command timeout (attempt {attempt + 1}/{retries}): {str(e)}")
                
            except subprocess.CalledProcessError as e:
                last_error = e.stderr.strip()
                self.logger.error(f"PM2 command failed (attempt {attempt + 1}/{retries}): {e.stderr}")
                
            except Exception as e:
                last_error = str(e)
                self.logger.error(f"Unexpected error (attempt {attempt + 1}/{retries}): {str(e)}")
            
            if attempt < retries - 1:
                self.logger.info(f"Retrying in {self.config.RETRY_DELAY} seconds...")
                time.sleep(self.config.RETRY_DELAY)
        
        raise PM2CommandError(f"Command failed after {retries} attempts: {last_error}")
    
    def is_fatal_error(self, error_msg: str) -> bool:
        """Determine if an error should prevent retries"""
        fatal_patterns = [
            "authentication failed",
            "permission denied",
            "repository not found",
            "could not resolve host",
            "no such file or directory",
            "invalid configuration"
        ]
        error_lower = error_msg.lower()
        return any(pattern in error_lower for pattern in fatal_patterns)

    def run_deploy_command(self, process_name: str, command: str = "") -> Dict:
        """Run PM2 deploy command with retries and force flag"""
        config_path = Path(f"/home/pm2/pm2-configs/{process_name}.config.js")
        
        if not config_path.exists():
            raise ProcessNotFoundError(f"Config file not found for {process_name}")
            
        cmd = f"pm2 deploy {config_path} production"
        if command:
            cmd += f" {command}"
        cmd += " --force"
        
        retry_delays = [1, 5, 15]  # Progressive retry delays
        last_error = None
        
        for attempt, delay in enumerate(retry_delays, 1):
            result = self.execute(cmd)
            if result["success"]:
                return result
                
            last_error = result.get("error", "Unknown error")
            if self.is_fatal_error(last_error):
                break
                
            if attempt < len(retry_delays):
                self.logger.warning(
                    f"Command failed (attempt {attempt}/{len(retry_delays)}), "
                    f"retrying in {delay} seconds... Error: {last_error}"
                )
                time.sleep(delay)
        
        raise PM2CommandError(f"Deploy command failed: {last_error}")
