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
import shutil
import webbrowser

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

    def uninstall_game(self, game_name: str, version: str) -> bool:
        """Удалить игру с устройства"""
        try:
            game_path = self.install_dir / game_name / version
            if game_path.exists():
                shutil.rmtree(game_path)
                logging.info(f"Successfully uninstalled {game_name} {version}")
                
                # Удаляем родительскую папку если она пустая
                parent_dir = self.install_dir / game_name
                if parent_dir.exists() and not any(parent_dir.iterdir()):
                    parent_dir.rmdir()
                    
                return True
            return False
        except Exception as e:
            logging.error(f"Uninstall error: {e}")
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
        
        # Современная цветовая схема
        bg = '#1a1a1a'
        fg = '#ffffff'
        accent = '#00d4ff'
        secondary = '#2d2d2d'
        hover = '#3d3d3d'
        card_bg = '#252525'
        success = '#00ff88'
        warning = '#ffaa00'
        danger = '#ff4444'
        
        style.configure('.', background=bg, foreground=fg, fieldbackground=bg)
        style.configure('TFrame', background=bg)
        style.configure('TLabel', background=bg, foreground=fg, font=('Segoe UI', 10))
        style.configure('Title.TLabel', background=bg, foreground=fg, font=('Segoe UI', 14, 'bold'))
        style.configure('TButton', background=secondary, foreground=fg, borderwidth=0, 
                       focuscolor='none', font=('Segoe UI', 9))
        style.map('TButton', background=[('active', hover), ('pressed', accent)])
        
        # Стили для разных кнопок
        style.configure('Accent.TButton', background=accent, foreground='#000000')
        style.map('Accent.TButton', background=[('active', '#00aaff'), ('pressed', '#0088cc')])
        
        style.configure('Success.TButton', background=success, foreground='#000000')
        style.map('Success.TButton', background=[('active', '#00cc66'), ('pressed', '#00aa55')])
        
        style.configure('Danger.TButton', background=danger, foreground='#ffffff')
        style.map('Danger.TButton', background=[('active', '#ff6666'), ('pressed', '#cc3333')])
        
        style.configure('TEntry', fieldbackground=secondary, foreground=fg, insertcolor=fg)
        style.configure('TProgressbar', background=accent, troughcolor=secondary)
        style.configure('Treeview', background=card_bg, fieldbackground=card_bg, foreground=fg,
                       rowheight=25)
        style.map('Treeview', background=[('selected', accent)])
        style.configure('Vertical.TScrollbar', background=secondary, troughcolor=bg)
        style.configure('Horizontal.TScrollbar', background=secondary, troughcolor=bg)
        
        # Стиль для карточек игр
        style.configure('GameCard.TFrame', background=card_bg, relief='raised', borderwidth=1)
        
        root.configure(bg=bg)

class GameCard(ttk.Frame):
    def __init__(self, parent, game_data, on_install, on_launch, on_uninstall, installed=False):
        super().__init__(parent, style='GameCard.TFrame')
        self.game_data = game_data
        self.on_install = on_install
        self.on_launch = on_launch
        self.on_uninstall = on_uninstall
        self.installed = installed
        
        self.setup_ui()

    def setup_ui(self):
        main_frame = ttk.Frame(self, style='GameCard.TFrame')
        main_frame.pack(fill='x', padx=15, pady=10)
        
        # Заголовок и версия
        header_frame = ttk.Frame(main_frame, style='GameCard.TFrame')
        header_frame.pack(fill='x', pady=(0, 5))
        
        ttk.Label(header_frame, text=self.game_data['name'], 
                 font=('Segoe UI', 12, 'bold'), style='TLabel').pack(side='left')
        
        version_label = ttk.Label(header_frame, text=f"v{self.game_data['version']}", 
                                 font=('Segoe UI', 9), foreground='#cccccc')
        version_label.pack(side='right')
        
        # Описание
        desc_frame = ttk.Frame(main_frame, style='GameCard.TFrame')
        desc_frame.pack(fill='x', pady=5)
        ttk.Label(desc_frame, text=self.game_data['description'], 
                 wraplength=600, style='TLabel').pack(anchor='w')
        
        # Информация о системе
        info_frame = ttk.Frame(main_frame, style='GameCard.TFrame')
        info_frame.pack(fill='x', pady=8)
        
        ttk.Label(info_frame, text=f"📦 {self.game_data['file_size']} MB", 
                 font=('Segoe UI', 9)).pack(side='left', padx=(0, 20))
        ttk.Label(info_frame, text=f"💾 {self.game_data['required_ram']} GB RAM", 
                 font=('Segoe UI', 9)).pack(side='left', padx=(0, 20))
        ttk.Label(info_frame, text=f"💿 {self.game_data['required_storage']} GB Storage", 
                 font=('Segoe UI', 9)).pack(side='left')
        
        # Кнопки действий
        button_frame = ttk.Frame(main_frame, style='GameCard.TFrame')
        button_frame.pack(fill='x', pady=(10, 0))
        
        if self.installed:
            ttk.Button(button_frame, text="🎮 Launch", 
                      command=lambda: self.on_launch(self.game_data),
                      style='Success.TButton').pack(side='left', padx=(0, 10))
            ttk.Button(button_frame, text="🗑️ Uninstall", 
                      command=lambda: self.on_uninstall(self.game_data),
                      style='Danger.TButton').pack(side='left')
        else:
            ttk.Button(button_frame, text="⬇️ Install", 
                      command=lambda: self.on_install(self.game_data),
                      style='Accent.TButton').pack(side='left')

class PintuxxGameLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Pintuxx Game Launcher")
        self.root.geometry("1400x900")
        self.root.minsize(1200, 800)
        
        # Версия лаунчера
        self.launcher_version = "1.1.0"
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
        file_menu.add_command(label="Check for Updates", command=self.check_for_updates)
        file_menu.add_command(label="Refresh", command=self.load_games)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Installation Directory", command=self.change_install_dir)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
        help_menu.add_command(label="Changelog", command=self.show_changelog)
        help_menu.add_command(label="Copyright", command=self.show_copyright)
        
    def setup_main_frame(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill='both', expand=True, padx=25, pady=20)
        
        # Заголовок с версией
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill='x', pady=(0, 20))
        
        ttk.Label(header_frame, text="Pintuxx Game Launcher", 
                 font=('Segoe UI', 20, 'bold'), style='Title.TLabel').pack(side='left')
        
        version_label = ttk.Label(header_frame, text=f"v{self.launcher_version}", 
                                 font=('Segoe UI', 12), foreground='#00d4ff')
        version_label.pack(side='left', padx=(10, 0))
        
        # Статистика
        stats_frame = ttk.Frame(main_frame)
        stats_frame.pack(fill='x', pady=(0, 15))
        
        self.stats_label = ttk.Label(stats_frame, text="Loading...", font=('Segoe UI', 10))
        self.stats_label.pack(anchor='w')
        
        self.setup_games_frame(main_frame)
        self.setup_downloads_frame(main_frame)

    def setup_games_frame(self, parent):
        games_frame = ttk.LabelFrame(parent, text="🎮 Available Games", padding=10)
        games_frame.pack(fill='both', expand=True, pady=10)
        
        # Поиск и фильтры
        search_frame = ttk.Frame(games_frame)
        search_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Label(search_frame, text="Search:").pack(side='left')
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        search_entry.pack(side='left', padx=(5, 20))
        search_entry.bind('<KeyRelease>', self.on_search)
        
        ttk.Button(search_frame, text="Clear", command=self.clear_search).pack(side='left')
        
        self.games_container = ttk.Frame(games_frame)
        self.games_container.pack(fill='both', expand=True)
        
        # Прокручиваемая область для карточек
        canvas_frame = ttk.Frame(self.games_container)
        canvas_frame.pack(fill='both', expand=True)
        
        self.canvas = tk.Canvas(canvas_frame, bg='#1a1a1a', highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Привязываем прокрутку колесиком мыши
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def setup_downloads_frame(self, parent):
        downloads_frame = ttk.LabelFrame(parent, text="📥 Active Downloads", padding=10)
        downloads_frame.pack(fill='x', pady=10)
        
        self.downloads_tree = ttk.Treeview(downloads_frame, 
                                         columns=('game', 'version', 'progress', 'status'), 
                                         show='headings', height=4)
        self.downloads_tree.heading('game', text='Game')
        self.downloads_tree.heading('version', text='Version')
        self.downloads_tree.heading('progress', text='Progress')
        self.downloads_tree.heading('status', text='Status')
        
        self.downloads_tree.column('game', width=250)
        self.downloads_tree.column('version', width=120)
        self.downloads_tree.column('progress', width=200)
        self.downloads_tree.column('status', width=150)
        
        self.downloads_tree.pack(fill='x')

    def on_search(self, event=None):
        """Фильтрация игр по поиску"""
        search_term = self.search_var.get().lower()
        for widget in self.scrollable_frame.winfo_children():
            if hasattr(widget, 'game_data'):
                game_name = widget.game_data['name'].lower()
                game_desc = widget.game_data['description'].lower()
                if search_term in game_name or search_term in game_desc:
                    widget.pack(fill='x', pady=5)
                else:
                    widget.pack_forget()

    def clear_search(self):
        """Очистить поиск"""
        self.search_var.set("")
        self.on_search()

    def load_games(self):
        try:
            self.server_handler = SecureRequestHandler("http://biggod.pythonanywhere.com", verify_ssl=False)
            status, response = self.server_handler._make_request('/games.json')
            if status == 200:
                games_data = json.loads(response.decode('utf-8'))
                self.game_manager.update_cache(games_data)
                self.display_games(games_data)
                self.update_stats()
                logging.info("Successfully loaded games from server")
            else:
                logging.warning(f"Server returned status {status}, using cache")
                self.display_games(self.game_manager.cache.get("games", {}))
                self.update_stats()
        except Exception as e:
            logging.error(f"Error loading games: {e}")
            self.display_games(self.game_manager.cache.get("games", {}))
            self.update_stats()

    def update_stats(self):
        """Обновить статистику"""
        installed_games = self.game_manager.get_installed_games()
        total_installed = sum(len(versions) for versions in installed_games.values())
        self.stats_label.config(text=f"📊 Total installed: {total_installed} games")

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
                self.uninstall_game,  # Новая функция удаления
                installed
            )
            card.pack(fill='x', pady=8)

    def queue_download(self, game_data: Dict):
        if game_data['name'] not in self.active_downloads:
            download_url = f"http://biggod.pythonanywhere.com/{game_data['download_path'].lstrip('/')}"
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
        status = '✅ Completed' if success else '❌ Failed'
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
                logging.info(f"Launched game: {game_data['name']}")
            except Exception as e:
                logging.error(f"Failed to launch game: {e}")
                messagebox.showerror("Error", "Failed to launch game")
        else:
            messagebox.showwarning("Warning", "No executable found")

    def uninstall_game(self, game_data: Dict):
        """Удалить игру с устройства"""
        game_name = game_data['name']
        version = game_data['version']
        
        confirm = messagebox.askyesno(
            "Confirm Uninstall",
            f"Are you sure you want to uninstall {game_name} {version}?\n\n"
            f"This will remove all game files from your device."
        )
        
        if confirm:
            success = self.game_manager.uninstall_game(game_name, version)
            if success:
                messagebox.showinfo("Success", f"{game_name} {version} has been uninstalled!")
                self.load_games()  # Обновляем список игр
                logging.info(f"User uninstalled {game_name} {version}")
            else:
                messagebox.showerror("Error", f"Failed to uninstall {game_name}")

    def change_install_dir(self):
        from tkinter import filedialog
        new_dir = filedialog.askdirectory()
        if new_dir:
            self.game_manager.install_dir = Path(new_dir)
            self.load_games()
            messagebox.showinfo("Success", f"Installation directory changed to: {new_dir}")
    def show_copyright(self):
        copyright_text = """
Copyright Notice - Pintuxx Game Launcher

LAUNCHER SOFTWARE:
© 2025 Pintuxx Games.  Developed by DeveloperCreation. All rights reserved.
GitHub: https://github.com/DEVELOPERcreatinon
This launcher application is my original work.

THIRD-PARTY GAMES:
• All games distributed through this launcher are property of their respective copyright holders
• I claim NO ownership or rights to any games unless explicitly marked as "Created by me"
• This launcher acts as a distribution platform only
• Game titles, characters, logos, and assets belong to their original creators

USER RESPONSIBILITY:
• Users are responsible for ensuring they have rights to download and use content
• By installing games, users acknowledge they understand copyright terms

REMOVAL REQUESTS:
If you are a copyright holder and want content removed, contact: superlohich@mail.ru
We will promptly remove infringing content.

Created games are clearly marked with author attribution.
        """
        self._show_clickable_message("Copyright Notice", copyright_text.strip())

    def show_about(self):
        about_text = f"""
    Pintuxx Game Launcher v{self.launcher_version}
    
    A modern game launcher with automatic updates,
    secure downloads, and easy game management.
    
    Features:
    • One-click game installation
    • Automatic updates
    • Secure file verification
    • Download management
    • Game uninstallation
    • Modern dark theme
    
    © 2025 Pintuxx Games. All rights reserved.
    Developed by: DeveloperCreation
    GitHub: https://github.com/DEVELOPERcreatinon
    """
        # Создаем отдельное окно с возможностью копирования
        self._show_clickable_message("About", about_text)
    
    def _show_clickable_message(self, title: str, text: str):
        """Показать сообщение с кликабельными ссылками"""
        top = tk.Toplevel(self.root)
        top.title(title)
        top.geometry("600x400")
        top.configure(bg='#1a1a1a')
        top.transient(self.root)
        top.grab_set()
        
        # Текст с прокруткой
        text_frame = ttk.Frame(top)
        text_frame.pack(fill='both', expand=True, padx=20, pady=20)
        
        text_widget = tk.Text(
            text_frame, 
            wrap='word', 
            bg='#1a1a1a', 
            fg='#ffffff',
            font=('Segoe UI', 10),
            borderwidth=0,
            relief='flat',
            cursor='arrow'
        )
        
        scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        
        text_widget.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Вставляем текст
        text_widget.insert('1.0', text)
        text_widget.config(state='normal')
        
        # Делаем ссылки кликабельными
        self._make_links_clickable(text_widget)
        
        # Кнопка закрытия
        ttk.Button(
            top, 
            text="Close", 
            command=top.destroy,
            style='Accent.TButton'
        ).pack(pady=10)
    
    def _make_links_clickable(self, text_widget):
        """Сделать ссылки в текстовом виджете кликабельными"""
        # Находим URL в тексте
        content = text_widget.get('1.0', 'end-1c')
        import re
        
        # Ищем URL-адреса
        urls = re.findall(r'https?://[^\s]+', content)
        
        for url in urls:
            # Находим начало и конец URL в тексте
            start_idx = content.find(url)
            if start_idx != -1:
                end_idx = start_idx + len(url)
                
                # Добавляем тег к URL
                text_widget.tag_add(url, f"1.0+{start_idx}c", f"1.0+{end_idx}c")
                text_widget.tag_config(url, foreground='#00d4ff', underline=True)
                
                # Привязываем обработчик клика
                text_widget.tag_bind(url, '<Button-1>', lambda e, url=url: self._open_url(url))
                text_widget.tag_bind(url, '<Enter>', lambda e: text_widget.config(cursor='hand2'))
                text_widget.tag_bind(url, '<Leave>', lambda e: text_widget.config(cursor='arrow'))
        
        # Делаем текст только для чтения
        text_widget.config(state='disabled')
    
    def _open_url(self, url: str):
        """Открыть URL в браузере по умолчанию"""
        try:
            import webbrowser
            webbrowser.open(url)
            logging.info(f"Opened URL: {url}")
        except Exception as e:
            logging.error(f"Failed to open URL {url}: {e}")
            messagebox.showerror("Error", f"Failed to open link: {e}")

    def show_changelog(self):
        changelog_text = """
🎉 Pintuxx Game Launcher v1.1.0 - Major Update 🎉

NEW FEATURES:
✨ Added game uninstallation functionality
🎨 Completely redesigned modern dark UI
🔍 Added search and filter for games
📊 Added installation statistics
🚀 Improved performance and loading times

IMPROVEMENTS:
• Enhanced game cards with better visuals
• Added progress indicators
• Improved download management
• Better error handling
• Smoother scrolling experience

BUG FIXES:
• Fixed download resuming issues
• Improved file verification
• Fixed memory leaks
• Better handling of network errors

SECURITY:
• Enhanced SSL verification
• Improved checksum validation
• Secure file handling

Update your games and enjoy the new experience! 🎮
        """
        self._show_clickable_message("Changelog", changelog_text.strip())



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
                    messagebox.showinfo("Updates", "🎉 You have the latest version!")
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
            f"🎉 New version {latest_version} is available!\n\n"
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
            temp_dir = Path("temp_update")
            temp_dir.mkdir(exist_ok=True)
            
            temp_file = temp_dir / "launcher_new.exe"
            
            handler = SecureRequestHandler(download_url, verify_ssl=False)
            status, response = handler._make_request('')
            
            if status == 200:
                with open(temp_file, 'wb') as f:
                    f.write(response)
                
                expected_checksum = update_info.get('checksum')
                if expected_checksum and not self._verify_file_checksum(temp_file, expected_checksum):
                    messagebox.showerror("Update Error", "Checksum verification failed!")
                    temp_file.unlink()
                    return
                
                self._create_update_script(temp_file)
                
                messagebox.showinfo("Update", "Update downloaded! Launcher will restart to apply update.")
                self.root.quit()
                
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
        
        bat_content = f"""@echo off
echo Updating Pintuxx Game Launcher...
timeout /t 2 /nobreak >nul

:wait
tasklist /fi "imagename eq {current_exe.name}" | find "{current_exe.name}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)

copy /Y "{new_exe}" "{current_exe}" >nul
start "" "{current_exe}"
del "{new_exe}" >nul
rd "{new_exe.parent}" >nul 2>&1
del "%~f0" >nul
"""
        
        bat_file = Path("update_launcher.bat")
        with open(bat_file, 'w') as f:
            f.write(bat_content)
        
        subprocess.Popen([str(bat_file)], shell=True)

if __name__ == "__main__":
    launcher = PintuxxGameLauncher()
    launcher.run()

