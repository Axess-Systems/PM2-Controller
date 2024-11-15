# services/process/deployer.py
def _run_command(self, cmd: str, timeout: int = 300, max_retries: int = 3) -> Dict:
    """Execute command with retries and timeout"""
    last_error = None
    
    for attempt in range(max_retries):
        try:
            self.logger.info(f"Running command (attempt {attempt + 1}/{max_retries}): {cmd}")
            
            # Use Popen for better process control
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(os.environ, PM2_SILENT='true'),
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )

            # Use a separate thread to read output
            stdout_data = []
            stderr_data = []

            def read_output():
                while True:
                    stdout_line = process.stdout.readline()
                    if stdout_line:
                        stdout_data.append(stdout_line)
                    stderr_line = process.stderr.readline()
                    if stderr_line:
                        stderr_data.append(stderr_line)
                    if not stdout_line and not stderr_line and process.poll() is not None:
                        break

            # Start output reading in thread
            from threading import Thread
            output_thread = Thread(target=read_output)
            output_thread.daemon = True
            output_thread.start()

            # Wait for process with timeout
            try:
                process.wait(timeout=timeout)
                output_thread.join(timeout=1)  # Give thread time to finish reading

                if process.returncode == 0:
                    return {
                        "success": True,
                        "output": ''.join(stdout_data)
                    }
                else:
                    last_error = ''.join(stderr_data) or ''.join(stdout_data) or str(process.returncode)

            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)  # Give process time to terminate
                except subprocess.TimeoutExpired:
                    process.kill()  # Force kill if still running
                last_error = f"Command timed out after {timeout} seconds"

            self.logger.error(f"Command failed (attempt {attempt + 1}/{max_retries}): {last_error}")

            if attempt < max_retries - 1:
                time.sleep(5)
                
        except Exception as e:
            last_error = str(e)
            self.logger.error(f"Unexpected error (attempt {attempt + 1}/{max_retries}): {last_error}")
            if attempt < max_retries - 1:
                time.sleep(5)

    return {
        "success": False,
        "error": last_error or "Command failed after all retries"
    }