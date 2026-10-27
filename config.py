from pathlib import Path
import json
import sys
import os
import socket

class Config:
    """Configuration manager for Mfano Bora Attachment System"""
    
    # Class-level configuration attributes
    DATABASE_URL = "sqlite:///./mfano_bora_attachment.db"
    SERVER_HOST = "0.0.0.0"
    SERVER_PORT = 8002
    UPLOAD_DIR = None  # Will be set dynamically
    
    @staticmethod
    def is_frozen():
        """Check if running as compiled executable"""
        return getattr(sys, 'frozen', False)
    
    @staticmethod
    def get_app_data_root():
        """Get the root application data directory"""
        if Config.is_frozen():
            # Running as compiled EXE - use AppData
            app_data = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
            base_dir = app_data / '.mfano_bora_attachment'
        else:
            # Running as script - use home folder
            base_dir = Path.home() / '.mfano_bora_attachment'
        
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir
    
    @staticmethod
    def get_data_dir():
        """Get data directory"""
        data_dir = Config.get_app_data_root() / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir
    
    @classmethod
    def get_offline_data_dir(cls):
        """Get directory for offline data storage"""
        offline_dir = cls.get_app_data_root() / 'offline'
        offline_dir.mkdir(parents=True, exist_ok=True)
        return offline_dir
    
    @classmethod
    def get_offline_queue_path(cls):
        """Get path for offline operations queue database"""
        return cls.get_offline_data_dir() / 'offline_queue.db'
    
    @classmethod
    def get_offline_cache_path(cls):
        """Get path for offline cache database"""
        return cls.get_offline_data_dir() / 'cache.db'
    
    @classmethod
    def get_base_directory(cls):
        """Get the base directory where the application is running"""
        if getattr(sys, 'frozen', False):
            # Running as compiled executable
            return Path(os.path.dirname(sys.executable))
        else:
            # Running as script
            return Path(__file__).parent
    
    @classmethod
    def get_database_path(cls):
        """Get the database path"""
        data_dir = cls.get_data_dir()
        db_path = data_dir / "mfano_bora_attachment.db"
        
        # Update DATABASE_URL to use the correct path
        cls.DATABASE_URL = f"sqlite:///{db_path}"
        
        # If database doesn't exist in persistent location, check if there's an existing one
        if not db_path.exists():
            # Check in application directory (development mode)
            app_dir = cls.get_base_directory()
            app_db_path = app_dir / "mfano_bora_attachment.db"
            if app_db_path.exists() and not db_path.exists():
                import shutil
                print(f"📋 Migrating database from {app_db_path} to {db_path}")
                shutil.copy2(app_db_path, db_path)
        
        return db_path
    
    @classmethod
    def get_uploads_path(cls):
        """Get the uploads path"""
        uploads_dir = cls.get_data_dir() / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        cls.UPLOAD_DIR = uploads_dir
        return uploads_dir
    
    @classmethod
    def ensure_config_dir(cls):
        """Ensure config directory exists"""
        config_dir = cls.get_app_data_root()
        config_dir.mkdir(parents=True, exist_ok=True)
        cls.get_data_dir().mkdir(parents=True, exist_ok=True)
        cls.get_offline_data_dir().mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def save_config(cls, config):
        """Save configuration to file"""
        config_dir = cls.get_app_data_root()
        config_file = config_dir / "config.json"
        config_dir.mkdir(parents=True, exist_ok=True)
        
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"💾 Config saved to: {config_file}")
    
    @classmethod
    def load_config(cls):
        """Load configuration from file"""
        config_file = cls.get_app_data_root() / "config.json"
        
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    print(f"📖 Config loaded from: {config_file}")
                    return config
            except Exception as e:
                print(f"⚠️ Error loading config: {e}")
                return {}
        return {}
    
    @classmethod
    def get_server_url(cls):
        """Get server URL from config or default"""
        config = cls.load_config()
        mode = config.get('last_mode', 'server')
        
        if mode == 'client':
            ip = config.get('server_ip', '127.0.0.1')
            return f"http://{ip}:{cls.SERVER_PORT}"
        else:
            return f"http://127.0.0.1:{cls.SERVER_PORT}"
    
    @classmethod
    def set_server_url(cls, url):
        """Set server URL"""
        if url.startswith('http://'):
            url = url[7:]
        ip = url.split(':')[0]
        cls.set_server_ip(ip)
    
    @classmethod
    def get_server_ip(cls):
        """Get server IP from config"""
        config = cls.load_config()
        return config.get('server_ip', '127.0.0.1')
    
    @classmethod
    def set_server_ip(cls, ip):
        """Set server IP in config"""
        config = cls.load_config()
        config['server_ip'] = ip
        cls.save_config(config)
    
    @classmethod
    def get_mode(cls):
        """Get the current mode (server/client)"""
        config = cls.load_config()
        return config.get('last_mode', None)
    
    @classmethod
    def set_mode(cls, mode, server_ip=None):
        """Set the mode and optionally server IP"""
        config = cls.load_config()
        config['last_mode'] = mode
        
        if mode == 'client' and server_ip:
            config['server_ip'] = server_ip
        elif mode == 'client' and not server_ip:
            if 'server_ip' not in config:
                config['server_ip'] = '127.0.0.1'
        
        cls.save_config(config)
    
    @classmethod
    def get_local_ip(cls):
        """Get local machine IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    @classmethod
    def get_all_paths(cls):
        """Debug method to show all paths"""
        print("\n" + "="*50)
        print("MFANO BORA ATTACHMENT SYSTEM - CONFIGURATION PATHS")
        print("="*50)
        print(f"Running as: {'EXE' if cls.is_frozen() else 'Script'}")
        print(f"App data root: {cls.get_app_data_root()}")
        print(f"Config file: {cls.get_app_data_root() / 'config.json'}")
        print(f"Data directory: {cls.get_data_dir()}")
        print(f"Offline data directory: {cls.get_offline_data_dir()}")
        print(f"Offline queue path: {cls.get_offline_queue_path()}")
        print(f"Offline cache path: {cls.get_offline_cache_path()}")
        print(f"Database path: {cls.get_database_path()}")
        print(f"Database URL: {cls.DATABASE_URL}")
        print(f"Uploads path: {cls.get_uploads_path()}")
        print("="*50 + "\n")
    
    @classmethod
    def get_offline_size(cls):
        """Get total size of offline data in bytes"""
        offline_dir = cls.get_offline_data_dir()
        total_size = 0
        if offline_dir.exists():
            for item in offline_dir.rglob('*'):
                if item.is_file():
                    total_size += item.stat().st_size
        return total_size
    
    @classmethod
    def clear_offline_data(cls):
        """Clear all offline data (cache and queue)"""
        offline_dir = cls.get_offline_data_dir()
        if offline_dir.exists():
            import shutil
            shutil.rmtree(offline_dir)
            offline_dir.mkdir(parents=True, exist_ok=True)
            print(f"🗑️ Cleared offline data directory: {offline_dir}")
            return True
        return False


# Initialize paths on module load
Config.get_database_path()  # This sets DATABASE_URL
Config.get_uploads_path()   # This sets UPLOAD_DIR
Config.get_offline_data_dir()  # Ensure offline directory exists

if __name__ == "__main__":
    Config.get_all_paths()