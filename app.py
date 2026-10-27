"""
Mfano Bora Africa Ltd - Attachment Management System
Entry Point
WITH OFFLINE SUPPORT - Creates and manages offline components
"""

import sys
import threading
import uvicorn # type: ignore
import os
import time
from pathlib import Path
import socket
import subprocess
import platform
import traceback
from datetime import datetime

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QTimer

from client.startup_dialog import StartupDialog
from client.main_window import MainWindow
from client.common.message_box_style import LIGHT_MESSAGE_BOX_STYLE
from config import Config

# ==================== IMPORT OFFLINE COMPONENTS ====================
from client.offline_manager import OfflineManager
from client.offline_cache import OfflineCache


import asyncio
import logging

# Suppress WinError 10054 noise on Windows
if hasattr(asyncio, 'WindowsProactorEventLoopPolicy'):
    logging.getLogger('asyncio').setLevel(logging.CRITICAL) 

# ==================== LOGGING FOR RELEASE VERSION ====================
if getattr(sys, 'frozen', False):
    # Running as compiled EXE
    log_dir = Path.home() / ".mfano_bora_attachment"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "release_debug.log"
    
    # Redirect stdout and stderr to file
    sys.stdout = open(log_file, 'w', encoding='utf-8')
    sys.stderr = open(log_file, 'a', encoding='utf-8')
    
    print(f"\n{'='*60}")
    print(f"RELEASE VERSION STARTED at {datetime.now()}")
    print(f"Executable: {sys.executable}")
    print(f"Log file: {log_file}")
    print(f"{'='*60}\n")

# Global variables
SERVER_PORT = 8002
HTTPS_PORT = 8443
backend_process = None
https_backend_process = None
server_ready = False


def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)


def get_local_ips():
    """Get all local IP addresses of this machine"""
    ips = []
    try:
        hostname = socket.gethostname()
        for addr in socket.gethostbyname_ex(hostname)[2]:
            if not addr.startswith("127."):
                ips.append(addr)
    except:
        pass
    
    if not ips:
        ips.append("127.0.0.1")
    
    return ips


def is_https_available():
    """Check if HTTPS certificates are available for web interface"""
    cert_path = get_resource_path("cert.pem")
    key_path = get_resource_path("key.pem")
    
    cert_exists = os.path.exists(cert_path)
    key_exists = os.path.exists(key_path)
    
    if cert_exists and key_exists:
        print(f"✅ HTTPS certificates found at: {cert_path}")
        return True
    else:
        print(f"⚠️ HTTPS certificates not found. cert_exists={cert_exists}, key_exists={key_exists}")
        return False


def start_backend():
    """Start FastAPI backend server (HTTP for desktop)"""
    global server_ready
    
    try:
        base_dir = Config.get_base_directory()
        
        if getattr(sys, 'frozen', False):
            if str(base_dir) not in sys.path:
                sys.path.insert(0, str(base_dir))
        
        os.chdir(str(base_dir))
        
        # Check if port is in use
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', SERVER_PORT))
        if result == 0:
            print(f"⚠️ Port {SERVER_PORT} is already in use!")
            sock.close()
        sock.close()
        
        import main
        
        main.DB_PATH = str(Config.get_database_path())
        main.UPLOAD_DIR = Config.get_uploads_path()
        
        Config.get_database_path().parent.mkdir(parents=True, exist_ok=True)
        Config.get_uploads_path().mkdir(parents=True, exist_ok=True)
        
        print(f"🚀 Starting HTTP server (Desktop) on 0.0.0.0:{SERVER_PORT}")
        print(f"📁 Database path: {main.DB_PATH}")
        
        config = uvicorn.Config(
            "main:app",
            host="0.0.0.0",
            port=SERVER_PORT,
            reload=False,
            log_level="info",
            workers=1
        )
        server = uvicorn.Server(config)
        
        server_ready = True
        print("✅ HTTP Backend server started successfully (Desktop app)")
        
        server.run()
        
    except Exception as e:
        print(f"❌ Failed to start backend: {e}")
        traceback.print_exc()
        server_ready = False


def start_https_backend():
    """Start HTTPS server for web interface (camera support)"""
    global https_backend_process
    
    if not is_https_available():
        print("⚠️ HTTPS certificates not found. Web interface camera will not work.")
        return
    
    try:
        base_dir = Config.get_base_directory()
        os.chdir(str(base_dir))
        
        import main
        
        print(f"🔒 Starting HTTPS server (Web Interface) on 0.0.0.0:{HTTPS_PORT}")
        
        cert_path = get_resource_path("cert.pem")
        key_path = get_resource_path("key.pem")
        
        print(f"   Using certificate: {cert_path}")
        print(f"   Using key: {key_path}")
        
        config = uvicorn.Config(
            "main:app",
            host="0.0.0.0",
            port=HTTPS_PORT,
            reload=False,
            log_level="info",
            workers=1,
            ssl_keyfile=key_path,
            ssl_certfile=cert_path
        )
        server = uvicorn.Server(config)
        
        print(f"✅ HTTPS Server started for web interface on port {HTTPS_PORT}")
        print(f"   Web interface URL: https://{Config.get_local_ip()}:{HTTPS_PORT}")
        
        https_backend_process = True
        server.run()
        
    except Exception as e:
        print(f"❌ Failed to start HTTPS backend: {e}")
        traceback.print_exc()
        https_backend_process = False


def wait_for_server(timeout=30):
    """Wait for HTTP server to become ready (Desktop app)"""
    print(f"⏳ Waiting for HTTP server to start...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            import requests
            response = requests.get(f"http://127.0.0.1:{SERVER_PORT}/health", timeout=2)
            if response.status_code == 200:
                print("✅ HTTP Server is ready!")
                return True
        except:
            pass
        time.sleep(0.5)
    
    print("❌ HTTP Server failed to start within timeout")
    return False


def show_server_info():
    """Display server information"""
    print("\n" + "="*50)
    print("🚀 MFANO BORA ATTACHMENT SYSTEM - SERVER RUNNING")
    print("="*50)
    
    local_ips = get_local_ips()
    print("\n📡 Server Connection Information:")
    print(f"   Desktop App Port: {SERVER_PORT} (HTTP)")
    
    if is_https_available():
        print(f"   Web Interface Port: {HTTPS_PORT} (HTTPS)")
    
    print("\n🌐 Connect clients using one of these addresses:")
    
    print("\n   DESKTOP APP (HTTP):")
    for ip in local_ips:
        if ip != "127.0.0.1":
            print(f"   → http://{ip}:{SERVER_PORT}")
    
    if is_https_available():
        print("\n   WEB INTERFACE (HTTPS):")
        for ip in local_ips:
            if ip != "127.0.0.1":
                print(f"   → https://{ip}:{HTTPS_PORT}")
        
        print("\n⚠️  Web Interface Security Warning:")
        print("   You'll see a security warning - this is normal")
        print("   Click 'Advanced' → 'Proceed to site' to continue")
    
    print("\n💻 For local access:")
    print(f"   Desktop: http://127.0.0.1:{SERVER_PORT}")
    if is_https_available():
        print(f"   Web: https://127.0.0.1:{HTTPS_PORT}")
    
    print("="*50 + "\n")


def main():
    """Main entry point - WITH OFFLINE SUPPORT"""
    global backend_thread, https_backend_thread
    
    # Create QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("Mfano Bora Attachment System")
    app.setStyleSheet(LIGHT_MESSAGE_BOX_STYLE)
    
    print("="*50)
    print("🏢 MFANO BORA AFRICA LTD - ATTACHMENT SYSTEM")
    print("="*50)
    print(f"📁 Application Directory: {Config.get_base_directory()}")
    print(f"📁 Database Path: {Config.get_database_path()}")
    print(f"📁 Config Directory: {Config.get_app_data_root()}")
    print(f"📁 Running as: {'EXE' if getattr(sys, 'frozen', False) else 'Script'}")
    print(f"🔒 HTTPS Available for Web: {is_https_available()}")
    print("="*50 + "\n")
    
    # ========== CREATE OFFLINE COMPONENTS FIRST ==========
    offline_manager = OfflineManager()
    offline_cache = OfflineCache()
    
    # Check for pending operations
    pending_count = offline_manager.get_count()
    if pending_count > 0:
        print(f"📋 Found {pending_count} pending offline operations from previous session")
    
    cached_count = len(offline_cache.get_all_users()) if offline_cache else 0
    if cached_count > 0:
        print(f"📦 Found {cached_count} cached users for offline access")
    
    # Check if we already have a saved configuration
    saved_mode = Config.get_mode()
    saved_ip = Config.get_server_ip()
    
    # If saved configuration exists, use it directly without showing dialog
    if saved_mode:
        print(f"📋 Found saved configuration: mode={saved_mode}, ip={saved_ip}")
        
        # Use saved configuration
        mode = saved_mode
        server_ip = saved_ip if saved_mode == 'client' else '127.0.0.1'
        
        # Start directly without dialog - PASS OFFLINE COMPONENTS
        start_with_config(mode, server_ip, offline_manager, offline_cache)
        
    else:
        # No saved configuration, show startup dialog - PASS OFFLINE COMPONENTS
        print("🆕 First time setup - showing configuration dialog")
        dialog = StartupDialog(offline_manager=offline_manager, offline_cache=offline_cache)
        
        if dialog.exec():
            config_data = dialog.get_config()
            mode = config_data.get('mode', 'server')
            server_ip = config_data.get('ip', '127.0.0.1')
            
            # Save configuration for next time
            Config.set_mode(mode, server_ip if mode == 'client' else None)
            
            start_with_config(mode, server_ip, offline_manager, offline_cache)
        else:
            print("Setup cancelled")
            sys.exit(0)


def start_with_config(mode, server_ip, offline_manager=None, offline_cache=None):
    """Start the system with the given configuration - WITH OFFLINE SUPPORT"""
    global backend_thread, https_backend_thread
    
    print(f"🚀 Starting with mode: {mode}, server_ip: {server_ip}")
    
    if mode == 'server':
        # Start as server
        print("🖥️ Starting in SERVER mode...")
        
        # Start HTTP backend for desktop app
        backend_thread = threading.Thread(target=start_backend, daemon=True)
        backend_thread.start()
        
        # Start HTTPS backend for web interface if certificates exist
        if is_https_available():
            https_backend_thread = threading.Thread(target=start_https_backend, daemon=True)
            https_backend_thread.start()
        
        # Wait for HTTP server to be ready (desktop app needs this)
        time.sleep(2)
        if wait_for_server(timeout=15):
            show_server_info()
            
            # Show success message (only on first run or when explicitly needed)
            first_run_flag = Config.get_app_data_root() / "first_run_done"
            if not first_run_flag.exists():
                message = f"Server is running!\n\n"
                message += f"Desktop App access: http://127.0.0.1:{SERVER_PORT}\n"
                
                if is_https_available():
                    message += f"Web Interface access: https://{Config.get_local_ip()}:{HTTPS_PORT}\n\n"
                    message += f"⚠️  Web users will see a security warning - click 'Advanced' → 'Proceed'\n\n"
                else:
                    message += f"Web Interface: Not available (run 'python generate_cert.py' to enable)\n\n"
                
                message += f"✓ Configuration saved to: {Config.get_app_data_root()}"
                
                if offline_manager and offline_manager.get_count() > 0:
                    message += f"\n\n📋 Note: {offline_manager.get_count()} pending offline operations will sync when clients connect."
                
                QMessageBox.information(None, "Server Started", message)
                first_run_flag.touch()
        else:
            QMessageBox.warning(None, "Warning", 
                "Server started but may not be fully ready. Some features may be unavailable.")
        
        # Set server IP to localhost for local client
        Config.set_server_ip("127.0.0.1")
        
    else:
        # Start as client
        print(f"💻 Starting in CLIENT mode, connecting to {server_ip}")
        Config.set_server_ip(server_ip)
        
        # Test connection (HTTP for desktop client) - NON-BLOCKING
        try:
            import requests
            response = requests.get(f"http://server_ip:{SERVER_PORT}/health", timeout=3)
            if response.status_code == 200:
                print("✅ Successfully connected to server")
                
                if offline_manager and offline_manager.get_count() > 0:
                    print(f"📋 Found {offline_manager.get_count()} pending operations - will sync when connected")
                
            else:
                print(f"⚠️ Server responded with status: {response.status_code}")
                QMessageBox.warning(None, "Connection Warning", 
                    f"Connected to server but got unexpected response.\n\n"
                    f"Server: {server_ip}:{SERVER_PORT}\n\n"
                    f"The application will continue, but some features may not work.\n\n"
                    f"Note: You may still work offline with cached data.")
        except Exception as e:
            print(f"⚠️ Connection test failed: {e}")
            has_cached_users = offline_cache and len(offline_cache.get_all_users()) > 0 if offline_cache else False
            
            if has_cached_users:
                QMessageBox.information(None, "Offline Mode Available", 
                    f"Could not connect to server at {server_ip}:{SERVER_PORT}\n\n"
                    f"However, you have cached data from previous logins.\n\n"
                    f"The application will start in OFFLINE MODE.\n"
                    f"Changes will be saved locally and synced when connection is restored.\n\n"
                    f"To reconfigure, delete the config file at:\n{Config.get_app_data_root()}")
            else:
                QMessageBox.warning(None, "Connection Warning", 
                    f"Could not verify connection to server.\n\n"
                    f"Server: {server_ip}:{SERVER_PORT}\n"
                    f"Error: {str(e)}\n\n"
                    f"The application will continue, but please check your connection.\n\n"
                    f"Note: No cached data available for offline access.\n\n"
                    f"To reconfigure, delete the config file at:\n{Config.get_app_data_root()}")
    
    # ========== SINGLE MAIN WINDOW CREATION (FIXED) ==========
    # Only ONE MainWindow created for BOTH server and client modes
    print("🔐 Opening login window with offline support...")
    main_window = MainWindow(
        offline_manager=offline_manager,
        offline_cache=offline_cache
    )
    main_window.show()
    
    sys.exit(QApplication.exec())


if __name__ == "__main__":
    main()
