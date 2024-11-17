# core/config.py
class Config:
    """Application configuration management"""
    
    def __init__(self):
        # Server Configuration
        self.PORT = int(os.environ.get('PORT', 5000))
        self.HOST = os.environ.get('HOST', '0.0.0.0')
        self.DEBUG = True  # Force debug mode on
        
        # Logging Configuration
        self.LOG_LEVEL = 'DEBUG'  # Force debug logging
        self.LOG_FORMAT = '%(asctime)s - %(name)s - [%(levelname)s] - %(message)s'
        self.LOG_FILE = os.environ.get('LOG_FILE', 'logs/pm2_controller.log')
        self.LOG_MAX_BYTES = int(os.environ.get('LOG_MAX_BYTES', 10485760))
        self.LOG_BACKUP_COUNT = int(os.environ.get('LOG_BACKUP_COUNT', 5))
        
        # PM2 Configuration with debug flags
        self.PM2_BIN = os.environ.get('PM2_BIN', 'pm2')
        self.MAX_LOG_LINES = int(os.environ.get('MAX_LOG_LINES', 1000))
        self.COMMAND_TIMEOUT = int(os.environ.get('COMMAND_TIMEOUT', 30))
        self.MAX_RETRIES = int(os.environ.get('MAX_RETRIES', 3))
        self.RETRY_DELAY = int(os.environ.get('RETRY_DELAY', 1))
        
        # File Paths
        self.PM2_CONFIG_DIR = Path('/home/pm2/pm2-configs')
        self.PYTHON_WRAPPER_DIR = Path('/home/pm2/pm2-configs')
        
        self._create_required_directories()

# services/process/deployer.py
class ProcessDeployer(Process):
    def run(self):
        """Execute deployment process"""
        try:
            self.logger.info(f"Starting deployment for process: {self.name}")
            self.logger.debug(f"Config data: {self.config_data}")
            
            # Create directories with explicit logging
            base_path = Path("/home/pm2")
            config_dir = base_path / "pm2-configs"
            process_dir = base_path / "pm2-processes" / self.name
            logs_dir = process_dir / "logs"

            for directory in [config_dir, process_dir, logs_dir]:
                directory.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"Directory created/verified: {directory}")

            # Print current directory state
            self.logger.debug(f"Base directory contents: {list(base_path.glob('*'))}")
            self.logger.debug(f"Config directory contents: {list(config_dir.glob('*'))}")
            
            # Create config file with logging
            self.logger.debug("Generating PM2 config file...")
            config_path = self.pm2_service.generate_config(
                name=self.name,
                repo_url=self.config_data['repository']['url'],
                script=self.config_data.get('script', 'main.py'),
                branch=self.config_data['repository'].get('branch', 'main'),
                cron=self.config_data.get('cron'),
                auto_restart=self.config_data.get('auto_restart', True),
                env_vars=self.config_data.get('env_vars')
            )
            
            # Log config file contents
            self.logger.debug(f"Config file created at: {config_path}")
            with open(config_path, 'r') as f:
                self.logger.debug(f"Config file contents:\n{f.read()}")

            # Run setup command with verbose output
            setup_cmd = f"{self.config.PM2_BIN} deploy {config_path} production setup --force"
            self.logger.debug(f"Running setup command: {setup_cmd}")
            
            setup_result = subprocess.run(
                setup_cmd,
                shell=True,
                capture_output=True,
                text=True,
                env=dict(os.environ, PM2_DEBUG='true')
            )
            
            self.logger.debug(f"Setup command stdout:\n{setup_result.stdout}")
            self.logger.debug(f"Setup command stderr:\n{setup_result.stderr}")
            
            if setup_result.returncode != 0:
                raise PM2CommandError(f"Setup failed with return code {setup_result.returncode}:\n"
                                   f"STDOUT: {setup_result.stdout}\n"
                                   f"STDERR: {setup_result.stderr}")

            # Continue with deploy if setup succeeds
            deploy_cmd = f"{self.config.PM2_BIN} deploy {config_path} production --force"
            self.logger.debug(f"Running deploy command: {deploy_cmd}")
            
            deploy_result = subprocess.run(
                deploy_cmd,
                shell=True,
                capture_output=True,
                text=True,
                env=dict(os.environ, PM2_DEBUG='true')
            )
            
            self.logger.debug(f"Deploy command stdout:\n{deploy_result.stdout}")
            self.logger.debug(f"Deploy command stderr:\n{deploy_result.stderr}")
            
            if deploy_result.returncode != 0:
                raise PM2CommandError(f"Deploy failed with return code {deploy_result.returncode}:\n"
                                   f"STDOUT: {deploy_result.stdout}\n"
                                   f"STDERR: {deploy_result.stderr}")

            self.result_queue.put({
                "success": True,
                "message": f"Process {self.name} deployed successfully",
                "config_file": str(config_path),
                "details": {
                    "setup_output": setup_result.stdout,
                    "deploy_output": deploy_result.stdout
                }
            })

        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}", exc_info=True)
            self.cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e),
                "traceback": traceback.format_exc()
            })

    def cleanup(self):
        """Clean up resources on failure"""
        try:
            self.logger.debug(f"Starting cleanup for failed deployment of {self.name}")
            
            # Clean up PM2 process if it exists
            pm2_delete = subprocess.run(
                f"{self.config.PM2_BIN} delete {self.name}",
                shell=True,
                capture_output=True,
                text=True
            )
            self.logger.debug(f"PM2 delete result: {pm2_delete.stdout} {pm2_delete.stderr}")

            # Clean up files with logging
            config_file = Path(f"/home/pm2/pm2-configs/{self.name}.config.js")
            process_dir = Path(f"/home/pm2/pm2-processes/{self.name}")

            if config_file.exists():
                config_file.unlink()
                self.logger.debug(f"Removed config file: {config_file}")

            if process_dir.exists():
                import shutil
                shutil.rmtree(process_dir)
                self.logger.debug(f"Removed process directory: {process_dir}")

        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}", exc_info=True)