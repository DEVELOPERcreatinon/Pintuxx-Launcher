import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import threading
import ssl
import http.client
import urllib.request
import urllib.parse
import hashlib
import zipfile
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import sys
import subprocess

class SecureRequestHandler:
    def __init__(self, base_url: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip('/')
        self.verify_ssl = verify_ssl
        self.context = ssl.create_default_context()
        if not verify_ssl:
            self.context.check_hostname = False
            self.context.verify_mode = ssl.CERT_NONE

    def _make_request(self, endpoint: str, method: str = 'GET', headers: Dict = None, data: bytes = None) -> Tuple[int, bytes]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        parsed = urllib.parse.urlparse(url)
        
        try:
            if parsed.scheme == 'https':
                conn = http.client.HTTPSConnection(parsed.netloc, context=self.context)
            else:
                conn = http.client.HTTPConnection(parsed.netloc)
            
            path = parsed.path
            if parsed.query:
                path += '?' + parsed.query
                
            conn.request(method, path, body=data, headers=headers or {})
            response = conn.getresponse()
            response_data = response.read()
            return response.status, response_data
        except Exception as e:
            logging.error(f"Request error: {e}")
            return 500, b''
        finally:
            conn.close()

class GameManager:
    def __init__(self, install_dir: str = "apps"):
        self.install_dir = Path(install_dir)
        self.install_dir.mkdir(exist_ok=True)
        self.cache_file = self.install_dir / "games_cache.json"
        self._load_cache()

    def _load_cache(self) -> None:
        if self.cache_file.exists():
            with open(self.cache_file, 'r') as f:
                self.cache = json.load(f)
        else:
            self.cache = {"games": {}, "last_update": 0}

    def _save_cache(self) -> None:
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f)

    def update_cache(self, games_data: Dict) -> None:
        self.cache["games"] = games_data
        self.cache["last_update"] = time.time()
        self._save_cache()

    def get_installed_games(self) -> Dict:
        installed = {}
        for game_dir in self.install_dir.iterdir():
            if game_dir.is_dir():
                versions = [v.name for v in game_dir.iterdir() if v.is_dir()]
                if versions:
                    installed[game_dir.name] = versions
        return installed

    def install_game(self, game_name: str, version: str, download_url: str, checksum: str, callback=None) -> bool:
        game_path = self.install_dir / game_name / version
        game_path.mkdir(parents=True, exist_ok=True)
        
        temp_file = game_path / f"{game_name}_{version}.tmp"
        final_file = game_path / f"{game_name}_{version}.zip"
        
        try:
            if self._download_file(download_url, temp_file, checksum, callback):
                temp_file.rename(final_file)
                if self._extract_archive(final_file, game_path):
                    final_file.unlink()
                    return True
        except Exception:
            if temp_file.exists():
                temp_file.unlink()
            if final_file.exists():
                final_file.unlink()
        return False

    def _download_file(self, url: str, dest: Path, expected_checksum: str, callback=None) -> bool:
        print(f"Starting download: {url} -> {dest}")
        
        handler = SecureRequestHandler(url)
        
        headers = {}
        if dest.exists():
            file_size = dest.stat().st_size
            headers['Range'] = f'bytes={file_size}-'
            print(f"Resuming download from byte {file_size}")
        
        try:
            status, response = handler._make_request('', headers=headers)
            print(f"Download status: {status}")
            print(f"Response length: {len(response)}")
            
            if status == 206:  # Partial Content
                mode = 'ab'
                print("Resuming partial download")
            elif status == 200:  # Full Content
                mode = 'wb'
                print("Starting new download")
            else:
                print(f"Download failed with status: {status}")
                return False
            
            with open(dest, mode) as f:
                f.write(response)
            
            print(f"File downloaded, size: {dest.stat().st_size} bytes")
            
            # Проверяем контрольную сумму
            if self._verify_checksum(dest, expected_checksum):
                print("Checksum verified successfully")
                return True
            else:
                print("Checksum verification failed")
                return False
                
        except Exception as e:
            print(f"Download error: {e}")
            return False

    def _verify_checksum(self, file_path: Path, expected: str) -> bool:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest() == expected

    def _extract_archive(self, archive_path: Path, extract_to: Path) -> bool:
        try:
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
            return True
        except zipfile.BadZipFile:
            return False

class DownloadWorker(threading.Thread):
    def __init__(self, game_manager: GameManager, game_data: Dict, install_dir: str, progress_callback=None, completion_callback=None):
        super().__init__()
        self.game_manager = game_manager
        self.game_data = game_data
        self.install_dir = install_dir
        self.progress_callback = progress_callback
        self.completion_callback = completion_callback
        self._stop_event = threading.Event()

    def run(self) -> None:
        # Используем полный URL для скачивания
        download_url = self.game_data.get('download_url', self.game_data['download_path'])
        success = self.game_manager.install_game(
            self.game_data['name'],
            self.game_data['version'],
            download_url,  # Передаем полный URL
            self.game_data['checksum'],
            self.progress_callback
        )
        if self.completion_callback:
            self.completion_callback(success, self.game_data)

    def stop(self) -> None:
        self._stop_event.set()

class ModernTheme:
    @staticmethod
    def apply(root):
        style = ttk.Style()
        style.theme_use('clam')
        
        bg = '#2b2b2b'
        fg = '#ffffff'
        accent = '#007acc'
        secondary = '#3c3c3c'
        hover = '#505050'
        
        style.configure('.', background=bg, foreground=fg, fieldbackground=bg)
        style.configure('TFrame', background=bg)
        style.configure('TLabel', background=bg, foreground=fg)
        style.configure('TButton', background=secondary, foreground=fg, borderwidth=0, focuscolor='none')
        style.map('TButton', background=[('active', hover), ('pressed', accent)])
        style.configure('TEntry', fieldbackground=secondary, foreground=fg, insertcolor=fg)
        style.configure('TProgressbar', background=accent, troughcolor=secondary)
        style.configure('Treeview', background=secondary, fieldbackground=secondary, foreground=fg)
        style.map('Treeview', background=[('selected', accent)])
        style.configure('Vertical.TScrollbar', background=secondary, troughcolor=bg)
        
        root.configure(bg=bg)

class GameCard(ttk.Frame):
    def __init__(self, parent, game_data, on_install, on_launch, installed=False):
        super().__init__(parent)
        self.game_data = game_data
        self.on_install = on_install
        self.on_launch = on_launch
        self.installed = installed
        
        self.setup_ui()

    def setup_ui(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(main_frame, text=self.game_data['name'], font=('Arial', 12, 'bold')).pack(anchor='w')
        ttk.Label(main_frame, text=f"Version: {self.game_data['version']}").pack(anchor='w')
        ttk.Label(main_frame, text=self.game_data['description']).pack(anchor='w')
        
        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill='x', pady=5)
        
        ttk.Label(info_frame, text=f"Size: {self.game_data['file_size']} MB").pack(side='left')
        ttk.Label(info_frame, text=f"RAM: {self.game_data['required_ram']} GB").pack(side='left', padx=20)
        ttk.Label(info_frame, text=f"Storage: {self.game_data['required_storage']} GB").pack(side='left')
        
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill='x', pady=5)
        
        if self.installed:
            ttk.Button(button_frame, text="Launch", command=lambda: self.on_launch(self.game_data)).pack(side='left')
        else:
            ttk.Button(button_frame, text="Install", command=lambda: self.on_install(self.game_data)).pack(side='left')





class PintuxxGameLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Pintuxx Game Launcher")
        self.root.geometry("1200x800")
        
        # Версия лаунчера
        self.launcher_version = "1.0.2"
        self.update_url = "http://biggod.pythonanywhere.com/launcher/update.json"
        
        ModernTheme.apply(self.root)
        
        self.game_manager = GameManager()
        self.server_handler = SecureRequestHandler("https://biggod.pythonanywhere.com")
        self.download_queue = []
        self.active_downloads = {}
        
        self.setup_logging()
        self.setup_ui()
        self.load_games()


        self._auto_check_updates()
    
    def _auto_check_updates(self):
        """Автоматически проверять обновления раз в день"""
        last_check_file = Path("last_update_check.txt")
        
        try:
            if last_check_file.exists():
                with open(last_check_file, 'r') as f:
                    last_check = float(f.read().strip())
                # Проверяем раз в день
                if time.time() - last_check < 86400:  # 24 часа
                    return
        except:
            pass
        
        # Сохраняем время проверки
        with open(last_check_file, 'w') as f:
            f.write(str(time.time()))
        
        # Запускаем проверку в фоне
        threading.Thread(target=self._background_update_check, daemon=True).start()
    
    def _background_update_check(self):
        """Фоновая проверка обновлений"""
        try:
            handler = SecureRequestHandler(self.update_url, verify_ssl=False)
            status, response = handler._make_request('')
            
            if status == 200:
                update_info = json.loads(response.decode('utf-8'))
                latest_version = update_info.get('version')
                
                if self._compare_versions(self.launcher_version, latest_version) < 0:
                    # Показываем уведомление в основном потоке
                    self.root.after(0, lambda: self._show_update_notification(update_info))
        except:
            pass  # Тихая проверка в фоне
    
    def _show_update_notification(self, update_info: Dict):
        """Показать уведомление об обновлении"""
        if messagebox.askyesno("Update Available", 
                              f"New version {update_info['version']} is available!\n\n"
                              f"Would you like to update now?"):
            self._perform_update(update_info['download_url'], update_info)
    
    

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('launcher.log'),
                logging.StreamHandler()
            ]
        )

    def setup_ui(self):
        self.setup_menu()
        self.setup_main_frame()

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Check for Updates", command=self.check_for_updates)  # НОВОЕ
        file_menu.add_command(label="Refresh", command=self.load_games)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Installation Directory", command=self.change_install_dir)

    def setup_main_frame(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)
        
        ttk.Label(main_frame, text="Pintuxx Game Launcher", font=('Arial', 16, 'bold')).pack(pady=10)
        
        self.setup_games_frame(main_frame)
        self.setup_downloads_frame(main_frame)

    def setup_games_frame(self, parent):
        games_frame = ttk.LabelFrame(parent, text="Available Games")
        games_frame.pack(fill='both', expand=True, pady=10)
        
        self.games_container = ttk.Frame(games_frame)
        self.games_container.pack(fill='both', expand=True, padx=10, pady=10)
        
        self.canvas = tk.Canvas(self.games_container, bg='#2b2b2b', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.games_container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def setup_downloads_frame(self, parent):
        downloads_frame = ttk.LabelFrame(parent, text="Active Downloads")
        downloads_frame.pack(fill='x', pady=10)
        
        self.downloads_tree = ttk.Treeview(downloads_frame, columns=('game', 'version', 'progress', 'status'), show='headings', height=3)
        self.downloads_tree.heading('game', text='Game')
        self.downloads_tree.heading('version', text='Version')
        self.downloads_tree.heading('progress', text='Progress')
        self.downloads_tree.heading('status', text='Status')
        
        self.downloads_tree.column('game', width=200)
        self.downloads_tree.column('version', width=100)
        self.downloads_tree.column('progress', width=150)
        self.downloads_tree.column('status', width=100)
        
        self.downloads_tree.pack(fill='x', padx=10, pady=10)

    def load_games(self):
        try:
            # Используем HTTP вместо HTTPS для локального сервера
            self.server_handler = SecureRequestHandler("http://biggod.pythonanywhere.com", verify_ssl=False)
            status, response = self.server_handler._make_request('/games.json')
            if status == 200:
                games_data = json.loads(response.decode('utf-8'))
                self.game_manager.update_cache(games_data)
                self.display_games(games_data)
                logging.info("Successfully loaded games from server")
            else:
                logging.warning(f"Server returned status {status}, using cache")
                self.display_games(self.game_manager.cache.get("games", {}))
        except Exception as e:
            logging.error(f"Error loading games: {e}")
            self.display_games(self.game_manager.cache.get("games", {}))

    def display_games(self, games_data: Dict):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        
        installed_games = self.game_manager.get_installed_games()
        
        for game_id, game_info in games_data.items():
            installed = game_info['name'] in installed_games and game_info['version'] in installed_games[game_info['name']]
            card = GameCard(
                self.scrollable_frame,
                game_info,
                self.queue_download,
                self.launch_game,
                installed
            )
            card.pack(fill='x', pady=5)

    def queue_download(self, game_data: Dict):
        if game_data['name'] not in self.active_downloads:
            # Создаем полный URL для скачивания
            download_url = f"http://biggod.pythonanywhere.com/{game_data['download_path'].lstrip('/')}"
            print(f"DEBUG: Game data: {game_data}")
            print(f"DEBUG: Download path from JSON: {game_data['download_path']}")
            print(f"DEBUG: Full download URL: {download_url}")
            game_data_with_full_url = game_data.copy()
            game_data_with_full_url['download_url'] = download_url
            
            self.download_queue.append(game_data_with_full_url)
            self.process_download_queue()
    
    def process_download_queue(self):
        if not self.download_queue or len(self.active_downloads) >= 3:
            return
        
        game_data = self.download_queue.pop(0)
        item_id = self.downloads_tree.insert('', 'end', values=(
            game_data['name'],
            game_data['version'],
            '0%',
            'Starting'
        ))
        
        worker = DownloadWorker(
            self.game_manager,
            game_data,
            self.game_manager.install_dir,
            lambda progress: self.update_progress(item_id, progress),
            lambda success, data: self.download_completed(success, data, item_id)
        )
        
        self.active_downloads[game_data['name']] = worker
        worker.start()

    def update_progress(self, item_id: str, progress: int):
        self.downloads_tree.set(item_id, 'progress', f'{progress}%')
        self.downloads_tree.set(item_id, 'status', 'Downloading')

    def download_completed(self, success: bool, game_data: Dict, item_id: str):
        status = 'Completed' if success else 'Failed'
        self.downloads_tree.set(item_id, 'status', status)
        
        if game_data['name'] in self.active_downloads:
            del self.active_downloads[game_data['name']]
        
        self.process_download_queue()
        self.load_games()

    def launch_game(self, game_data: Dict):
        game_path = self.game_manager.install_dir / game_data['name'] / game_data['version']
        exe_files = list(game_path.glob('*.exe'))
        
        if exe_files:
            try:
                subprocess.Popen([str(exe_files[0])], cwd=game_path)
            except Exception:
                messagebox.showerror("Error", "Failed to launch game")
        else:
            messagebox.showwarning("Warning", "No executable found")

    def change_install_dir(self):
        from tkinter import filedialog
        new_dir = filedialog.askdirectory()
        if new_dir:
            self.game_manager.install_dir = Path(new_dir)
            self.load_games()

    def run(self):
        self.root.mainloop()

    def check_for_updates(self):
        """Проверить обновления лаунчера"""
        try:
            handler = SecureRequestHandler(self.update_url, verify_ssl=False)
            status, response = handler._make_request('')
            
            if status == 200:
                update_info = json.loads(response.decode('utf-8'))
                latest_version = update_info.get('version')
                
                if self._compare_versions(self.launcher_version, latest_version) < 0:
                    self._ask_for_update(update_info)
                else:
                    messagebox.showinfo("Updates", "You have the latest version!")
            else:
                messagebox.showerror("Update Error", "Failed to check for updates")
        except Exception as e:
            logging.error(f"Update check error: {e}")
            messagebox.showerror("Update Error", f"Failed to check for updates: {e}")
    
    def _compare_versions(self, current: str, latest: str) -> int:
        """Сравнить версии (возвращает -1 если current < latest)"""
        current_parts = list(map(int, current.split('.')))
        latest_parts = list(map(int, latest.split('.')))
        
        for i in range(max(len(current_parts), len(latest_parts))):
            current_val = current_parts[i] if i < len(current_parts) else 0
            latest_val = latest_parts[i] if i < len(latest_parts) else 0
            
            if current_val < latest_val:
                return -1
            elif current_val > latest_val:
                return 1
        return 0
    
    def _ask_for_update(self, update_info: Dict):
        """Спросить пользователя об обновлении"""
        latest_version = update_info.get('version', 'Unknown')
        changes = update_info.get('changelog', 'No changelog available')
        download_url = update_info.get('download_url')
        file_size = update_info.get('file_size', 0)
        
        message = (
            f"New version {latest_version} is available!\n\n"
            f"Current version: {self.launcher_version}\n"
            f"File size: {file_size} MB\n\n"
            f"Changes:\n{changes}\n\n"
            "Do you want to update now?"
        )
        
        if messagebox.askyesno("Update Available", message):
            self._perform_update(download_url, update_info)
    
    def _perform_update(self, download_url: str, update_info: Dict):
        """Выполнить обновление"""
        try:
            # Создаем временную директорию для обновления
            temp_dir = Path("temp_update")
            temp_dir.mkdir(exist_ok=True)
            
            # Скачиваем новый лаунчер
            temp_file = temp_dir / "launcher_new.exe"
            
            handler = SecureRequestHandler(download_url, verify_ssl=False)
            status, response = handler._make_request('')
            
            if status == 200:
                with open(temp_file, 'wb') as f:
                    f.write(response)
                
                # Проверяем контрольную сумму
                expected_checksum = update_info.get('checksum')
                if expected_checksum and not self._verify_file_checksum(temp_file, expected_checksum):
                    messagebox.showerror("Update Error", "Checksum verification failed!")
                    temp_file.unlink()
                    return
                
                # Создаем батник для обновления
                self._create_update_script(temp_file)
                
                messagebox.showinfo("Update", "Update downloaded! Launcher will restart to apply update.")
                self.root.quit()  # Закрываем текущий лаунчер
                
            else:
                messagebox.showerror("Update Error", "Failed to download update")
                
        except Exception as e:
            logging.error(f"Update error: {e}")
            messagebox.showerror("Update Error", f"Update failed: {e}")
    
    def _verify_file_checksum(self, file_path: Path, expected_checksum: str) -> bool:
        """Проверить контрольную сумму файла"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest() == expected_checksum
    
    def _create_update_script(self, new_launcher_path: Path):
        """Создать скрипт для обновления (работает для Windows)"""
        current_exe = Path(sys.argv[0]).absolute()
        new_exe = new_launcher_path.absolute()
        
        # BAT файл для Windows
        bat_content = f"""@echo off
    echo Updating Pintuxx Game Launcher...
    timeout /t 2 /nobreak >nul
    
    :: Ждем пока старый лаунчер закроется
    :wait
    tasklist /fi "imagename eq {current_exe.name}" | find "{current_exe.name}" >nul
    if not errorlevel 1 (
        timeout /t 1 /nobreak >nul
        goto wait
    )
    
    :: Заменяем файл
    copy /Y "{new_exe}" "{current_exe}" >nul
    
    :: Запускаем новый лаунчер
    start "" "{current_exe}"
    
    :: Удаляем временные файлы
    del "{new_exe}" >nul
    rd "{new_exe.parent}" >nul 2>&1
    del "%~f0" >nul
    """
        
        bat_file = Path("update_launcher.bat")
        with open(bat_file, 'w') as f:
            f.write(bat_content)
        
        # Запускаем батник
        subprocess.Popen([str(bat_file)], shell=True)



if __name__ == "__main__":
    launcher = PintuxxGameLauncher()
    launcher.run()