#!/usr/bin/env python3
"""
AOS Service Restart Script with Visual Feedback and API Token Validation
This script stops the AOS service, cleans logs and data, then restarts the service
and validates the API token by testing the operation-mode endpoint

Version: 2.3.0 (Python)
Last Updated: 2025-07-07

Changelog:
v2.3.0 - Converted to Python for better maintainability and smaller size
v2.2.0 - Enhanced API authentication with multiple extraction fallbacks  
v2.1.0 - Added comprehensive API debugging and HTTP status checking
v2.0.0 - Added API authentication and admin password setting functionality
v1.5.0 - Added mount point detection and preservation for /var/lib/aos/db
"""

import argparse
import json
import os
import subprocess
import sys
import time
import shutil
import signal
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

class AOSManager:
    def __init__(self, show_exec: bool = False, verbose: bool = False):
        self.show_exec = show_exec
        self.verbose = verbose
        self.api_token = None
        self.admin_user_id = None
        self.base_url = "https://localhost:443"
        
    def print_status(self, message: str):
        print(f"{Colors.GREEN}[INFO]{Colors.NC} {message}")
    
    def print_warning(self, message: str):
        print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {message}")
    
    def print_error(self, message: str):
        print(f"{Colors.RED}[ERROR]{Colors.NC} {message}")
    
    def print_progress(self, message: str):
        print(f"{Colors.BLUE}[PROGRESS]{Colors.NC} {message}")
    
    def exec_cmd(self, cmd: str, description: str) -> bool:
        """Execute command with optional logging"""
        if self.show_exec:
            print(f"{Colors.CYAN}[EXEC]{Colors.NC} {description}")
            print(f"{Colors.CYAN}   └── Running:{Colors.NC} \"{cmd}\"")
        
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            success = result.returncode == 0
            
            if self.show_exec:
                color = Colors.GREEN if success else Colors.RED
                status = "Success" if success else "Failed"
                print(f"{color}   └── {status}{Colors.NC} (exit code: {result.returncode})")
                if not success and result.stderr:
                    print(f"   └── Error: {result.stderr.strip()}")
                print()
            
            return success
        except Exception as e:
            if self.show_exec:
                print(f"{Colors.RED}   └── Exception: {e}{Colors.NC}")
            return False
    
    def visual_wait(self, duration: int, message: str, style: str = "countdown"):
        """Wait with visual feedback"""
        if style == "countdown":
            for i in range(duration, 0, -1):
                print(f"\r{Colors.YELLOW}[WAIT]{Colors.NC} {message} {Colors.CYAN}{i}{Colors.NC} seconds remaining...", end="", flush=True)
                time.sleep(1)
            print(f"\r\033[K", end="")  # Clear line
            self.print_status(f"{message} completed")
        else:
            time.sleep(duration)
    
    def check_root(self) -> bool:
        """Check if running as root"""
        if os.geteuid() != 0:
            self.print_error("This script must be run as root or with sudo privileges")
            return False
        return True
    
    def check_port_443(self) -> bool:
        """Check if port 443 is listening"""
        try:
            # Try netstat first
            result = subprocess.run("netstat -tlpn 2>/dev/null | grep ':443 '", 
                                   shell=True, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return True
            
            # Try ss as fallback
            result = subprocess.run("ss -tlpn 2>/dev/null | grep ':443 '", 
                                   shell=True, capture_output=True, text=True)
            return result.returncode == 0 and result.stdout.strip()
        except:
            return False
    
    def is_mount_point(self, path: str) -> bool:
        """Check if path is a mount point"""
        try:
            result = subprocess.run(f"mountpoint -q '{path}'", shell=True)
            return result.returncode == 0
        except:
            return False
    
    def stop_aos_service(self) -> bool:
        """Stop AOS service and clean up processes"""
        self.print_status("Stopping AOS service...")
        
        if not self.exec_cmd("service aos stop", "Stop AOS service"):
            self.print_error("Failed to execute AOS service stop command")
            return False
        
        # Wait for service to stop
        for i in range(30):
            result = subprocess.run("service aos status", shell=True, capture_output=True)
            if result.returncode != 0:
                self.print_status("AOS service stopped successfully")
                break
            time.sleep(1)
        else:
            self.print_warning("Service may not have stopped properly")
        
        # Clean up processes
        self.print_status("Checking for remaining AOS processes...")
        try:
            result = subprocess.run("pgrep -f aos", shell=True, capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                script_pid = str(os.getpid())
                
                for pid in pids:
                    if pid != script_pid:
                        try:
                            os.kill(int(pid), signal.SIGTERM)
                            self.print_status(f"Terminated process {pid}")
                        except:
                            pass
                
                time.sleep(3)  # Wait for graceful termination
        except:
            pass
        
        self.visual_wait(5, "Waiting for file handles to be released", "spinner")
        return True
    
    def clean_logs(self) -> bool:
        """Clean AOS logs"""
        self.print_status("Cleaning AOS logs...")
        log_dir = Path("/var/log/aos")
        
        if not log_dir.exists():
            self.print_warning("AOS log directory does not exist")
            return True
        
        if not any(log_dir.iterdir()):
            self.print_status("AOS log directory is already empty")
            return True
        
        try:
            shutil.rmtree(log_dir)
            log_dir.mkdir(exist_ok=True)
            self.print_status("AOS logs cleaned successfully")
            return True
        except Exception as e:
            self.print_error(f"Failed to clean AOS logs: {e}")
            return False
    
    def clean_data(self) -> bool:
        """Clean AOS data with mount point preservation"""
        self.print_status("Cleaning AOS data...")
        data_dir = Path("/var/lib/aos")
        
        if not data_dir.exists():
            self.print_warning("AOS data directory does not exist")
            return True
        
        if not any(data_dir.iterdir()):
            self.print_status("AOS data directory is already empty")
            return True
        
        # Handle mount points
        mount_points = []
        for item in data_dir.iterdir():
            if item.is_dir() and self.is_mount_point(str(item)):
                mount_points.append(item)
                self.print_warning(f"🗻 Detected mount point: {item}")
        
        # Special handling for db mount point
        db_path = data_dir / "db"
        if db_path.exists() and self.is_mount_point(str(db_path)):
            self.print_status("🗻 /var/lib/aos/db is a mount point - cleaning contents only")
            try:
                for item in db_path.iterdir():
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                self.print_status("✅ DB mount point contents cleaned successfully")
            except Exception as e:
                self.print_warning(f"⚠️  Some DB mount point contents could not be removed: {e}")
        
        # Clean other items (preserve mount points)
        failed_items = []
        for item in data_dir.iterdir():
            if item.name in ['.', '..']:
                continue
            
            if self.is_mount_point(str(item)):
                self.print_status(f"🗻 Preserving mount point: {item}")
                continue
            
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                failed_items.append((item, e))
        
        if failed_items:
            self.print_warning("Some files could not be removed:")
            for item, error in failed_items:
                self.print_warning(f"  ❌ {item}: {error}")
            return False
        
        self.print_status("✅ AOS data directory cleaned successfully")
        if mount_points:
            self.print_status("🗻 Preserved mount points:")
            for mp in mount_points:
                print(f"  🗻 {mp}")
        
        return True
    
    def start_aos_service(self) -> bool:
        """Start AOS service and monitor webserver"""
        self.print_status("Starting AOS service...")
        
        if not self.exec_cmd("service aos start", "Start AOS service"):
            self.print_error("Failed to start AOS service")
            return False
        
        # Wait for service to start
        self.print_progress("Waiting for AOS service to start...")
        for i in range(60):
            result = subprocess.run("service aos status", shell=True, capture_output=True)
            if result.returncode == 0:
                self.print_status("AOS service started successfully")
                break
            time.sleep(1)
        else:
            self.print_warning("Service may not have started properly")
        
        # Wait for port 443
        self.print_status("Monitoring port 443 webserver startup...")
        for i in range(120):
            if self.check_port_443():
                self.print_status("Port 443 is now listening")
                break
            time.sleep(1)
        else:
            self.print_warning("Port 443 did not start listening within timeout")
            return False
        
        # Test basic connectivity
        self.visual_wait(5, "Allowing webserver to initialize")
        
        try:
            response = requests.get(self.base_url, verify=False, timeout=10)
            self.print_status("✅ Webserver is responding")
            return True
        except:
            self.print_warning("⚠️  Webserver connectivity test failed")
            return False
    
    def authenticate_api(self, username: str = "admin", password: str = "admin") -> bool:
        """Authenticate with AOS API and get token"""
        self.print_status("🔐 Authenticating with AOS API...")
        
        auth_url = f"{self.base_url}/api/aaa/login"
        payload = {"username": username, "password": password}
        
        for attempt in range(5):
            try:
                if attempt > 0:
                    self.print_status(f"Authentication attempt {attempt + 1}/5...")
                
                response = requests.post(auth_url, json=payload, verify=False, timeout=10)
                
                if self.show_exec:
                    self.print_status(f"HTTP Status: {response.status_code}")
                    self.print_status(f"Response length: {len(response.text)} bytes")
                
                # Accept both 200 (OK) and 201 (Created) as success
                if response.status_code in [200, 201]:
                    try:
                        data = response.json()
                        token = data.get('token')
                        
                        if token:
                            self.api_token = token
                            if self.show_exec:
                                self.print_status(f"✅ Token extracted (length: {len(token)} characters)")
                                self.print_status(f"Token preview: {token[:15]}...{token[-15:]}")
                            
                            self.print_status("✅ API authentication successful")
                            return True
                        else:
                            self.print_error("❌ No token in response")
                            if self.show_exec:
                                self.print_status(f"Response content: {response.text}")
                    
                    except json.JSONDecodeError as e:
                        self.print_error(f"❌ Failed to parse JSON response: {e}")
                        if self.show_exec:
                            self.print_status(f"Raw response: {response.text[:200]}")
                
                elif response.status_code == 401:
                    self.print_error("❌ HTTP 401 Unauthorized")
                elif response.status_code == 404:
                    self.print_error("❌ HTTP 404 Not Found - API endpoint may not be ready")
                elif response.status_code == 502:
                    self.print_error("❌ HTTP 502 Bad Gateway - API server not ready")
                elif response.status_code == 503:
                    self.print_error("❌ HTTP 503 Service Unavailable - API server starting up")
                else:
                    self.print_error(f"❌ HTTP {response.status_code} - {response.text[:100]}")
                
            except requests.exceptions.RequestException as e:
                self.print_error(f"❌ Request failed: {e}")
            except Exception as e:
                self.print_error(f"❌ Unexpected error: {e}")
                if self.show_exec:
                    self.print_status(f"Response text: {getattr(response, 'text', 'No response')[:200]}")
            
            if attempt < 4:
                self.print_status("⏳ Authentication failed, waiting 15 seconds before retry...")
                time.sleep(15)
        
        self.print_error("❌ Failed to authenticate after 5 attempts")
        return False
    
    def get_admin_user_id(self, username: str = "admin") -> bool:
        """Get admin user ID from API"""
        if not self.api_token:
            self.print_error("No API token available")
            return False
        
        self.print_status("👤 Retrieving admin user ID...")
        self.print_status("Calling GET /api/aaa/users to find admin user...")
        
        # Add a small delay to ensure API is ready
        time.sleep(2)
        
        users_url = f"{self.base_url}/api/aaa/users"
        
        # Try different header combinations with AuthToken
        header_combinations = [
            # Correct header based on API documentation
            {
                "AuthToken": self.api_token,
                "Accept": "application/json"
            },
            # Minimal with just AuthToken
            {
                "AuthToken": self.api_token
            }
        ]
        
        for attempt, headers in enumerate(header_combinations, 1):
            try:
                if self.show_exec:
                    self.print_status(f"Attempt {attempt}/4 with different headers...")
                
                response = requests.get(users_url, headers=headers, verify=False, timeout=10)
                
                if self.show_exec:
                    self.print_status(f"HTTP Status: {response.status_code}")
                    self.print_status(f"Response: {response.text}")
                
                # Accept various success codes
                if response.status_code in [200, 201, 202]:
                    try:
                        data = response.json()
                        items = data.get('items', [])
                        
                        self.print_status(f"✅ Successfully retrieved {len(items)} users from /api/aaa/users")
                        
                        for user in items:
                            if user.get('username') == username:
                                user_id = user.get('id')
                                if user_id:
                                    self.admin_user_id = user_id
                                    self.print_status(f"✅ Admin user ID retrieved: {user_id}")
                                    return True
                        
                        self.print_error(f"❌ Admin user '{username}' not found in response")
                        return False  # Found valid response but no admin user
                    
                    except json.JSONDecodeError as e:
                        if attempt < len(header_combinations):
                            continue  # Try next header combination
                        else:
                            self.print_error(f"❌ Failed to parse JSON response: {e}")
                            return False
                
                elif response.status_code == 401:
                    # Don't show individual attempts, just try different headers
                    if attempt < len(header_combinations):
                        continue  # Try next header combination
                    else:
                        self.print_error("❌ All header combinations failed with HTTP 401")
                        self.print_error("The API token seems to be rejected by /api/aaa/users endpoint")
                        
                        # Try one final re-authentication only if we haven't done it yet
                        if not hasattr(self, '_user_id_retry_done'):
                            self._user_id_retry_done = True
                            self.print_status("Trying re-authentication...")
                            if self.authenticate_api():
                                self.print_status("Re-authentication successful, retrying user lookup...")
                                return self.get_admin_user_id(username)
                        
                        return False
                
                elif response.status_code == 403:
                    self.print_error("❌ HTTP 403: API token doesn't have permission to list users")
                    return False
                elif response.status_code == 404:
                    self.print_error("❌ HTTP 404: /api/aaa/users endpoint not found")
                    return False
                elif response.status_code == 500:
                    if attempt < len(header_combinations):
                        continue  # Try next header combination
                    else:
                        self.print_error("❌ HTTP 500: Internal server error on /api/aaa/users")
                        return False
                else:
                    if attempt < len(header_combinations):
                        continue  # Try next header combination
                    else:
                        self.print_error(f"❌ /api/aaa/users returned HTTP {response.status_code}")
                        if self.show_exec:
                            self.print_status(f"Response: {response.text}")
                        return False
                
            except Exception as e:
                if attempt < len(header_combinations):
                    continue  # Try next header combination
                else:
                    self.print_error(f"❌ Exception calling /api/aaa/users: {e}")
                    return False
        
        return False
    
    def set_admin_password(self, new_password: str) -> bool:
        """Set admin user password using the retrieved user ID"""
        if not self.api_token or not self.admin_user_id:
            self.print_error("Missing API token or user ID")
            return False
        
        self.print_status("🔑 Setting admin user password...")
        
        password_url = f"{self.base_url}/api/aaa/users/{self.admin_user_id}/change-password"
        headers = {"AuthToken": self.api_token}
        payload = {
            "current_password": "admin",  # Default password after reset
            "new_password": new_password
        }
        
        try:
            response = requests.put(password_url, json=payload, headers=headers, verify=False, timeout=15)
            
            if self.show_exec:
                self.print_status(f"HTTP Status: {response.status_code}")
                self.print_status(f"Response length: {len(response.text)} bytes")
                if response.text:
                    self.print_status(f"Response: {response.text}")
            
            # Accept various success status codes
            if response.status_code in [200, 201, 202, 204]:
                self.print_status("✅ Admin password updated successfully")
                return True
            elif response.status_code == 401:
                self.print_error("❌ Password update failed: HTTP 401 Unauthorized")
                self.print_error("The API token may be invalid or expired")
            elif response.status_code == 403:
                self.print_error("❌ Password update failed: HTTP 403 Forbidden")
                self.print_error("The API token doesn't have permission to change passwords")
            elif response.status_code == 404:
                self.print_error("❌ Password update failed: HTTP 404 Not Found")
                self.print_error("The user ID may be incorrect or the endpoint doesn't exist")
            elif response.status_code == 422:
                self.print_error("❌ Password update failed: HTTP 422 Unprocessable Entity")
                self.print_error("The password may not meet requirements or request format is invalid")
            elif response.status_code == 500:
                self.print_error("❌ Password update failed: HTTP 500 Internal Server Error")
                self.print_error("The API server encountered an internal error")
            else:
                self.print_error(f"❌ Password update failed: HTTP {response.status_code}")
                if self.show_exec and response.text:
                    self.print_status(f"Response details: {response.text}")
                
        except Exception as e:
            self.print_error(f"❌ Password update failed: {e}")
        
        return False
    
    def verify_password_change(self, username: str = "admin", new_password: str = None) -> bool:
        """Verify that the password change was successful by trying to authenticate with new password"""
        if not new_password:
            self.print_error("No new password provided for verification")
            return False
        
        self.print_status("🔍 Verifying password change by testing new credentials...")
        
        if self.show_exec:
            self.print_status(f"Testing credentials - Username: '{username}', Password: '{new_password}'")
        
        auth_url = f"{self.base_url}/api/aaa/login"
        payload = {"username": username, "password": new_password}
        
        try:
            if self.show_exec:
                self.print_status(f"Making verification request to: {auth_url}")
                self.print_status(f"Payload: {payload}")
            
            response = requests.post(auth_url, json=payload, verify=False, timeout=10)
            
            if self.show_exec:
                self.print_status(f"Verification HTTP Status: {response.status_code}")
                self.print_status(f"Verification Response length: {len(response.text)} bytes")
                self.print_status(f"Verification Response: {response.text}")
            
            if response.status_code in [200, 201]:
                try:
                    data = response.json()
                    token = data.get('token')
                    
                    if token:
                        self.print_status("✅ Password change verified successfully - new credentials work!")
                        if self.show_exec:
                            self.print_status(f"Verification token received (length: {len(token)} characters)")
                        return True
                    else:
                        self.print_error("❌ Password verification failed - no token in response")
                        return False
                
                except json.JSONDecodeError:
                    self.print_error("❌ Password verification failed - invalid JSON response")
                    return False
            
            elif response.status_code == 401:
                self.print_error("❌ Password verification failed - new credentials rejected")
                self.print_error("The password change may not have taken effect")
                if self.show_exec:
                    self.print_status("This means the API is rejecting the new username/password combination")
                return False
            else:
                self.print_error(f"❌ Password verification failed - HTTP {response.status_code}")
                if self.show_exec:
                    self.print_status(f"Unexpected status code during verification")
                return False
                
        except Exception as e:
            self.print_error(f"❌ Password verification failed: {e}")
            return False

    def configure_admin_password(self, new_password: str = None) -> bool:
        """Complete API configuration workflow"""
        self.print_status("🔧 Starting post-restart API configuration...")
        print("=" * 50)
        
        # Use provided password or default
        if not new_password:
            new_password = "NewAdminPassword123!"
            self.print_warning("⚠️  No password specified, using default. Use --password to set a custom password.")
        else:
            self.print_status(f"🔑 Using specified password: {new_password}")
        
        # Step 1: Authenticate
        self.print_status("Step 1: Authenticating with default credentials...")
        if not self.authenticate_api():
            return False
        
        # Step 2: Get user ID
        self.print_status("Step 2: Retrieving admin user ID...")
        if not self.get_admin_user_id():
            return False
        
        # Step 3: Set password
        self.print_status("Step 3: Setting admin password...")
        
        if self.set_admin_password(new_password):
            # Step 4: Verify password change
            self.print_status("Step 4: Verifying password change...")
            if self.verify_password_change("admin", new_password):
                self.print_status("✅ Admin password configuration completed successfully")
                self.print_status(f"🔐 Admin user ID: {self.admin_user_id}")
                self.print_status("🔑 Password has been updated and verified")
                print("=" * 50)
                return True
            else:
                self.print_warning("⚠️  Password was set but verification failed")
                self.print_warning("You may need to check the password manually")
                print("=" * 50)
                return False
        else:
            self.print_error("❌ Failed to set admin password")
            print("=" * 50)
            return False
    
    def run_full_restart(self, admin_password: str = None) -> bool:
        """Execute complete restart workflow"""
        print("=" * 50)
        print("    AOS Service Restart Script v2.3.0")
        print("=" * 50)
        print()
        
        steps = [
            ("Stop AOS service", self.stop_aos_service),
            ("Clean logs", self.clean_logs),
            ("Clean data", self.clean_data),
            ("Start AOS service", self.start_aos_service),
        ]
        
        for step_name, step_func in steps:
            self.print_status(f"Executing: {step_name}")
            if not step_func():
                self.print_error(f"Failed at step: {step_name}")
                return False
        
        # API Configuration - Pass the password here
        print()
        if not self.configure_admin_password(admin_password):
            self.print_warning("API configuration failed, but service restart completed")
            return False
        
        print()
        self.print_status("🎉 AOS service restart and configuration completed successfully!")
        print("=" * 50)
        return True

def main():
    parser = argparse.ArgumentParser(description="AOS Service Restart Script v2.3.0")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("-e", "--exec", action="store_true", help="Show actual commands being executed")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--password", default="NewAdminPassword123!", help="New admin password")
    
    args = parser.parse_args()
    
    # Create manager instance
    manager = AOSManager(show_exec=args.exec, verbose=args.verbose)
    
    # Check root privileges
    if not manager.check_root():
        sys.exit(1)
    
    # Show confirmation unless -y flag is used
    if not args.yes:
        print("This script will perform the following actions:")
        print("  1. Stop AOS service")
        print("  2. Remove all files from /var/log/aos/")
        print("  3. Remove all files from /var/lib/aos/ (preserving mount points)")
        print("  4. Start AOS service")
        print("  5. Validate basic webserver functionality")
        print("  6. Authenticate with AOS API using default credentials")
        print("  7. Retrieve admin user ID from API")
        print("  8. Set admin user password via API")
        print()
        manager.print_warning("This will delete all AOS logs and data!")
        print()
        
        response = input("Are you sure you want to continue? (y/N): ")
        if response.lower() != 'y':
            manager.print_error("Aborted by user")
            sys.exit(1)
        print()
    
    # Execute full restart - Pass the password here!
    success = manager.run_full_restart(args.password)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()