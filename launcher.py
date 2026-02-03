# launcher_pyside.py
import sys
import json
import hashlib
import zipfile
import threading
import time
import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==================== СЕТЕВОЙ МОДУЛЬ ====================
class NetworkManager(QObject):
    """Менеджер сетевых запросов с поддержкой повторных попыток"""
    progress_updated = Signal(str, int, int)  # game_name, downloaded, total
    download_finished = Signal(str, bool)  # game_name, success
    download_error = Signal(str, str)  # game_name, error_message
    
    def __init__(self):
        super().__init__()
        self.session = self._create_session()
        self.active_downloads = {}
        
    def _create_session(self):
        """Создать сессию с повторными попытками"""
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session
        
    def download_file(self, url: str, dest_path: Path, game_name: str, expected_hash: str = None):
        """Скачать файл с прогресс-баром по байтам"""
        thread = threading.Thread(
            target=self._download_thread,
            args=(url, dest_path, game_name, expected_hash),
            daemon=True
        )
        thread.start()
        
    def _download_thread(self, url: str, dest_path: Path, game_name: str, expected_hash: str):
        """Поток для скачивания"""
        try:
            # Проверяем частично скачанный файл
            resume_byte = 0
            if dest_path.exists():
                resume_byte = dest_path.stat().st_size
                
            headers = {}
            if resume_byte:
                headers['Range'] = f'bytes={resume_byte}-'
                
            with self.session.get(url, headers=headers, stream=True, timeout=30) as response:
                response.raise_for_status()
                
                total_size = int(response.headers.get('content-length', 0))
                if resume_byte:
                    total_size += resume_byte
                    
                mode = 'ab' if resume_byte else 'wb'
                with open(dest_path, mode) as f:
                    downloaded = resume_byte
                    
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            self.progress_updated.emit(
                                game_name, 
                                downloaded, 
                                total_size if total_size > 0 else downloaded
                            )
                            
                # Проверяем хеш если указан
                if expected_hash and not self._verify_hash(dest_path, expected_hash):
                    raise ValueError("Checksum verification failed")
                    
                self.download_finished.emit(game_name, True)
                
        except Exception as e:
            self.download_error.emit(game_name, str(e))
            
    def _verify_hash(self, file_path: Path, expected_hash: str) -> bool:
        """Проверить MD5 хеш файла"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest() == expected_hash

# ==================== МЕНЕДЖЕР ИГР ====================
class GameManager(QObject):
    """Управление установленными играми"""
    game_installed = Signal(str)  # game_name
    game_uninstalled = Signal(str)  # game_name
    
    def __init__(self, install_dir: str = "games"):
        super().__init__()
        self.install_dir = Path(install_dir)
        self.install_dir.mkdir(exist_ok=True)
        self.cache_file = self.install_dir / "games_cache.json"
        self._load_cache()
        
    def _load_cache(self):
        """Загрузить кэш игр"""
        if self.cache_file.exists():
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                self.cache = json.load(f)
        else:
            self.cache = {"games": {}, "last_update": 0}
            
    def save_cache(self, games_data: Dict):
        """Сохранить кэш игр"""
        self.cache["games"] = games_data
        self.cache["last_update"] = time.time()
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=2, ensure_ascii=False)
            
    def get_installed_games(self) -> Dict:
        """Получить список установленных игр"""
        installed = {}
        for game_dir in self.install_dir.iterdir():
            if game_dir.is_dir() and (game_dir / "game.info").exists():
                try:
                    with open(game_dir / "game.info", 'r', encoding='utf-8') as f:
                        info = json.load(f)
                    installed[game_dir.name] = info
                except:
                    continue
        return installed
        
    def install_game(self, game_data: Dict, download_path: Path) -> bool:
        """Установить игру из архива"""
        try:
            game_name = game_data['name']
            version = game_data['version']
            game_folder = self.install_dir / f"{game_name}_{version}"
            game_folder.mkdir(exist_ok=True)
            
            # Распаковываем архив
            with zipfile.ZipFile(download_path, 'r') as zip_ref:
                zip_ref.extractall(game_folder)
                
            # Сохраняем информацию об игре
            game_info = {
                **game_data,
                "install_date": datetime.now().isoformat(),
                "install_path": str(game_folder.absolute())
            }
            
            with open(game_folder / "game.info", 'w', encoding='utf-8') as f:
                json.dump(game_info, f, indent=2, ensure_ascii=False)
                
            # Удаляем архив
            download_path.unlink()
            
            self.game_installed.emit(game_name)
            return True
            
        except Exception as e:
            print(f"Install error: {e}")
            return False
            
    def uninstall_game(self, game_name: str, version: str) -> bool:
        """Удалить игру"""
        try:
            game_folder = self.install_dir / f"{game_name}_{version}"
            if game_folder.exists():
                shutil.rmtree(game_folder)
                self.game_uninstalled.emit(game_name)
                return True
            return False
        except Exception as e:
            print(f"Uninstall error: {e}")
            return False
            
    def launch_game(self, game_info: Dict) -> bool:
        """Запустить игру"""
        try:
            game_path = Path(game_info['install_path'])
            exe_files = list(game_path.glob('*.exe')) + list(game_path.glob('*.bat'))
            
            if exe_files:
                subprocess.Popen(
                    [str(exe_files[0])],
                    cwd=game_path,
                    creationflags=subprocess.DETACHED_PROCESS
                )
                return True
            return False
        except Exception as e:
            print(f"Launch error: {e}")
            return False

# ==================== ВИДЖЕТЫ ====================
class GameCard(QFrame):
    """Карточка игры"""
    install_clicked = Signal(dict)
    launch_clicked = Signal(dict)
    uninstall_clicked = Signal(dict)
    
    def __init__(self, game_data: Dict, installed: bool = False):
        super().__init__()
        self.game_data = game_data
        self.installed = installed
        self.setup_ui()
        
    def setup_ui(self):
        self.setStyleSheet("""
            GameCard {
                background-color: #2d2d2d;
                border-radius: 10px;
                border: 1px solid #404040;
            }
            QLabel {
                color: #ffffff;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        
        # Заголовок
        header = QHBoxLayout()
        title_label = QLabel(self.game_data['name'])
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(title_label)
        
        version_label = QLabel(f"v{self.game_data['version']}")
        version_label.setStyleSheet("color: #888888; font-size: 12px;")
        header.addWidget(version_label, alignment=Qt.AlignRight)
        layout.addLayout(header)
        
        # Описание
        desc_label = QLabel(self.game_data['description'])
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #cccccc; font-size: 12px;")
        layout.addWidget(desc_label)
        
        # Информация
        info_layout = QHBoxLayout()
        info_items = [
            f"📦 {self.game_data.get('file_size', 'N/A')} MB",
            f"💾 {self.game_data.get('required_ram', 'N/A')} GB RAM",
        ]
        
        for item in info_items:
            label = QLabel(item)
            label.setStyleSheet("color: #888888; font-size: 11px;")
            info_layout.addWidget(label)
            
        info_layout.addStretch()
        layout.addLayout(info_layout)
        
        # Кнопки
        button_layout = QHBoxLayout()
        
        if self.installed:
            launch_btn = QPushButton("🎮 Launch")
            launch_btn.setStyleSheet("""
                QPushButton {
                    background-color: #00a67d;
                    color: white;
                    border-radius: 5px;
                    padding: 8px 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #00c995;
                }
            """)
            launch_btn.clicked.connect(lambda: self.launch_clicked.emit(self.game_data))
            button_layout.addWidget(launch_btn)
            
            uninstall_btn = QPushButton("🗑️ Uninstall")
            uninstall_btn.setStyleSheet("""
                QPushButton {
                    background-color: #d32f2f;
                    color: white;
                    border-radius: 5px;
                    padding: 8px 16px;
                }
                QPushButton:hover {
                    background-color: #f44336;
                }
            """)
            uninstall_btn.clicked.connect(lambda: self.uninstall_clicked.emit(self.game_data))
            button_layout.addWidget(uninstall_btn)
            
        else:
            install_btn = QPushButton("⬇️ Install")
            install_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196f3;
                    color: white;
                    border-radius: 5px;
                    padding: 8px 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #42a5f5;
                }
            """)
            install_btn.clicked.connect(lambda: self.install_clicked.emit(self.game_data))
            button_layout.addWidget(install_btn)
            
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setFixedHeight(180)

class DownloadItemWidget(QWidget):
    """Виджет активной загрузки"""
    def __init__(self, game_name: str, version: str):
        super().__init__()
        self.game_name = game_name
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        
        # Информация о загрузке
        info_layout = QHBoxLayout()
        name_label = QLabel(self.game_name)
        name_label.setStyleSheet("font-weight: bold; color: white;")
        info_layout.addWidget(name_label)
        
        self.status_label = QLabel("Starting...")
        self.status_label.setStyleSheet("color: #888888;")
        info_layout.addWidget(self.status_label, alignment=Qt.AlignRight)
        layout.addLayout(info_layout)
        
        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #404040;
                border-radius: 5px;
                text-align: center;
                background-color: #1a1a1a;
            }
            QProgressBar::chunk {
                background-color: #2196f3;
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Информация о размере
        self.size_label = QLabel("Calculating size...")
        self.size_label.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self.size_label)
        
    def update_progress(self, downloaded: int, total: int):
        """Обновить прогресс загрузки"""
        if total > 0:
            percentage = int((downloaded / total) * 100)
            self.progress_bar.setValue(percentage)
            
            # Форматирование размера
            downloaded_str = self._format_size(downloaded)
            total_str = self._format_size(total)
            self.size_label.setText(f"{downloaded_str} / {total_str}")
            self.status_label.setText("Downloading...")
            
    def set_completed(self, success: bool):
        """Установить статус завершения"""
        if success:
            self.progress_bar.setValue(100)
            self.status_label.setText("✅ Completed")
            self.status_label.setStyleSheet("color: #4caf50;")
        else:
            self.status_label.setText("❌ Failed")
            self.status_label.setStyleSheet("color: #f44336;")
            
    def _format_size(self, bytes_size: int) -> str:
        """Форматировать размер в читаемый вид"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} TB"

# ==================== ГЛАВНОЕ ОКНО ====================
class GameLauncher(QMainWindow):
    """Главное окно лаунчера"""
    def __init__(self):
        super().__init__()
        self.launcher_version = "2.0.0"
        self.server_url = "http://biggod.pythonanywhere.com"
        self.update_url = f"{self.server_url}/launcher/update.json"
        
        # Инициализация менеджеров
        self.network_manager = NetworkManager()
        self.game_manager = GameManager()
        
        # Настройка окна
        self.setWindowTitle(f"Pintuxx Game Launcher v{self.launcher_version}")
        self.setGeometry(100, 100, 1400, 900)
        self.setMinimumSize(1200, 800)
        
        # Настройка стилей
        self.setup_styles()
        
        # Настройка UI
        self.setup_ui()
        
        # Подключение сигналов
        self.setup_connections()
        
        # Загрузка игр
        QTimer.singleShot(100, self.load_games)
        
    def setup_styles(self):
        """Установка темных стилей"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
            }
            QLabel {
                color: #ffffff;
            }
            QPushButton {
                background-color: #2d2d2d;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QPushButton:pressed {
                background-color: #404040;
            }
            QLineEdit {
                background-color: #2d2d2d;
                color: white;
                border: 1px solid #404040;
                border-radius: 5px;
                padding: 5px;
            }
            QProgressBar {
                border: 1px solid #404040;
                border-radius: 5px;
                text-align: center;
                background-color: #1a1a1a;
            }
            QProgressBar::chunk {
                background-color: #2196f3;
                border-radius: 5px;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #2d2d2d;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #404040;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
    def setup_ui(self):
        """Настройка пользовательского интерфейса"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Заголовок
        header = QHBoxLayout()
        title_label = QLabel("Pintuxx Game Launcher")
        title_label.setStyleSheet("font-size: 28px; font-weight: bold; color: #00d4ff;")
        header.addWidget(title_label)
        
        version_label = QLabel(f"v{self.launcher_version}")
        version_label.setStyleSheet("font-size: 14px; color: #888888;")
        header.addWidget(version_label, alignment=Qt.AlignRight)
        main_layout.addLayout(header)
        
        # Статистика
        self.stats_label = QLabel("Loading games...")
        self.stats_label.setStyleSheet("font-size: 12px; color: #888888;")
        main_layout.addWidget(self.stats_label)
        
        # Поиск
        search_layout = QHBoxLayout()
        search_label = QLabel("🔍 Search:")
        search_layout.addWidget(search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search games...")
        self.search_input.textChanged.connect(self.filter_games)
        search_layout.addWidget(self.search_input)
        
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_search)
        search_layout.addWidget(clear_btn)
        
        search_layout.addStretch()
        
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.load_games)
        search_layout.addWidget(refresh_btn)
        
        main_layout.addLayout(search_layout)
        
        # Разделитель
        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)
        
        # Игры
        games_widget = QWidget()
        games_layout = QVBoxLayout(games_widget)
        games_layout.setSpacing(10)
        
        games_label = QLabel("🎮 Available Games")
        games_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        games_layout.addWidget(games_label)
        
        # Контейнер для игр с прокруткой
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.games_container = QWidget()
        self.games_layout = QVBoxLayout(self.games_container)
        self.games_layout.setSpacing(15)
        self.games_layout.setAlignment(Qt.AlignTop)
        
        scroll_area.setWidget(self.games_container)
        games_layout.addWidget(scroll_area)
        
        splitter.addWidget(games_widget)
        
        # Загрузки
        downloads_widget = QWidget()
        downloads_layout = QVBoxLayout(downloads_widget)
        downloads_layout.setSpacing(10)
        
        downloads_label = QLabel("📥 Active Downloads")
        downloads_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        downloads_layout.addWidget(downloads_label)
        
        self.downloads_container = QVBoxLayout()
        self.downloads_container.setSpacing(10)
        
        downloads_wrapper = QWidget()
        downloads_wrapper.setLayout(self.downloads_container)
        
        downloads_scroll = QScrollArea()
        downloads_scroll.setWidgetResizable(True)
        downloads_scroll.setWidget(downloads_wrapper)
        downloads_scroll.setMaximumHeight(200)
        downloads_layout.addWidget(downloads_scroll)
        
        splitter.addWidget(downloads_widget)
        
        # Меню
        self.setup_menu()
        
    def setup_menu(self):
        """Настройка меню"""
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #2d2d2d;
                color: white;
            }
            QMenuBar::item:selected {
                background-color: #3d3d3d;
            }
            QMenu {
                background-color: #2d2d2d;
                color: white;
                border: 1px solid #404040;
            }
            QMenu::item:selected {
                background-color: #3d3d3d;
            }
        """)
        
        # Файл
        file_menu = menubar.addMenu("File")
        file_menu.addAction("Check for Updates", self.check_updates)
        file_menu.addAction("Change Install Directory", self.change_install_dir)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)
        
        # Помощь
        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About", self.show_about)
        help_menu.addAction("Changelog", self.show_changelog)
        help_menu.addAction("Copyright", self.show_copyright)
        
    def setup_connections(self):
        """Подключение сигналов"""
        self.network_manager.progress_updated.connect(self.on_download_progress)
        self.network_manager.download_finished.connect(self.on_download_finished)
        self.network_manager.download_error.connect(self.on_download_error)
        
        self.game_manager.game_installed.connect(self.on_game_installed)
        self.game_manager.game_uninstalled.connect(self.on_game_uninstalled)
        
    def load_games(self):
        """Загрузить список игр"""
        try:
            response = requests.get(f"{self.server_url}/games.json", timeout=10)
            if response.status_code == 200:
                games_data = response.json()
                self.game_manager.save_cache(games_data)
                self.display_games(games_data)
            else:
                self.display_games(self.game_manager.cache.get("games", {}))
        except Exception as e:
            print(f"Error loading games: {e}")
            self.display_games(self.game_manager.cache.get("games", {}))
            
    def display_games(self, games_data: Dict):
        """Отобразить игры"""
        # Очищаем контейнер
        for i in reversed(range(self.games_layout.count())): 
            widget = self.games_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
                
        installed_games = self.game_manager.get_installed_games()
        
        for game_id, game_info in games_data.items():
            installed = any(
                game_info['name'] == info.get('name') and 
                game_info['version'] == info.get('version')
                for info in installed_games.values()
            )
            
            card = GameCard(game_info, installed)
            card.install_clicked.connect(self.install_game)
            card.launch_clicked.connect(self.launch_game)
            card.uninstall_clicked.connect(self.uninstall_game)
            
            self.games_layout.addWidget(card)
            
        # Обновляем статистику
        self.update_stats()
        
    def update_stats(self):
        """Обновить статистику"""
        installed = len(self.game_manager.get_installed_games())
        self.stats_label.setText(f"📊 Installed games: {installed}")
        
    def filter_games(self):
        """Фильтровать игры по поиску"""
        search_term = self.search_input.text().lower()
        
        for i in range(self.games_layout.count()):
            widget = self.games_layout.itemAt(i).widget()
            if isinstance(widget, GameCard):
                game_name = widget.game_data['name'].lower()
                game_desc = widget.game_data['description'].lower()
                
                if search_term in game_name or search_term in game_desc:
                    widget.show()
                else:
                    widget.hide()
                    
    def clear_search(self):
        """Очистить поиск"""
        self.search_input.clear()
        
    def install_game(self, game_data: Dict):
        """Начать установку игры"""
        # Создаем виджет загрузки
        download_widget = DownloadItemWidget(game_data['name'], game_data['version'])
        self.downloads_container.addWidget(download_widget)
        
        # Подготавливаем путь для скачивания
        temp_dir = Path("temp_downloads")
        temp_dir.mkdir(exist_ok=True)
        
        download_url = f"{self.server_url}/{game_data['download_path'].lstrip('/')}"
        dest_path = temp_dir / f"{game_data['name']}_{game_data['version']}.zip"
        
        # Запоминаем виджет для обновления
        download_widget.game_name = game_data['name']
        download_widget.dest_path = dest_path
        download_widget.game_data = game_data
        
        # Начинаем загрузку
        self.network_manager.download_file(
            download_url,
            dest_path,
            game_data['name'],
            game_data.get('checksum')
        )
        
    def on_download_progress(self, game_name: str, downloaded: int, total: int):
        """Обновить прогресс загрузки"""
        for i in range(self.downloads_container.count()):
            widget = self.downloads_container.itemAt(i).widget()
            if widget and widget.game_name == game_name:
                widget.update_progress(downloaded, total)
                break
                
    def on_download_finished(self, game_name: str, success: bool):
        """Загрузка завершена"""
        for i in range(self.downloads_container.count()):
            widget = self.downloads_container.itemAt(i).widget()
            if widget and widget.game_name == game_name:
                widget.set_completed(success)
                
                if success:
                    # Устанавливаем игру
                    QTimer.singleShot(1000, lambda w=widget: self.finalize_installation(w))
                else:
                    # Удаляем виджет через 3 секунды
                    QTimer.singleShot(3000, lambda w=widget: w.deleteLater())
                    
                break
                
    def finalize_installation(self, download_widget):
        """Завершить установку игры"""
        success = self.game_manager.install_game(
            download_widget.game_data,
            download_widget.dest_path
        )
        
        if success:
            QMessageBox.information(self, "Success", 
                                  f"{download_widget.game_data['name']} installed successfully!")
        else:
            QMessageBox.warning(self, "Error", 
                              f"Failed to install {download_widget.game_data['name']}")
                              
        # Обновляем список игр и удаляем виджет
        self.load_games()
        QTimer.singleShot(2000, download_widget.deleteLater)
        
    def on_download_error(self, game_name: str, error_msg: str):
        """Ошибка загрузки"""
        QMessageBox.critical(self, "Download Error", 
                           f"Failed to download {game_name}:\n{error_msg}")
                           
        # Удаляем виджет загрузки
        for i in range(self.downloads_container.count()):
            widget = self.downloads_container.itemAt(i).widget()
            if widget and widget.game_name == game_name:
                widget.deleteLater()
                break
                
    def launch_game(self, game_data: Dict):
        """Запустить игру"""
        installed_games = self.game_manager.get_installed_games()
        
        for info in installed_games.values():
            if (info.get('name') == game_data['name'] and 
                info.get('version') == game_data['version']):
                
                success = self.game_manager.launch_game(info)
                if not success:
                    QMessageBox.warning(self, "Launch Error", 
                                      "Failed to launch the game. Check if executable exists.")
                return
                
        QMessageBox.warning(self, "Not Installed", 
                          "Game is not installed!")
                          
    def uninstall_game(self, game_data: Dict):
        """Удалить игру"""
        reply = QMessageBox.question(
            self, "Confirm Uninstall",
            f"Are you sure you want to uninstall {game_data['name']} {game_data['version']}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success = self.game_manager.uninstall_game(
                game_data['name'],
                game_data['version']
            )
            
            if success:
                QMessageBox.information(self, "Success", 
                                      f"{game_data['name']} uninstalled successfully!")
                self.load_games()
            else:
                QMessageBox.warning(self, "Error", 
                                  f"Failed to uninstall {game_data['name']}")
                                  
    def change_install_dir(self):
        """Изменить директорию установки"""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Installation Directory"
        )
        
        if directory:
            self.game_manager.install_dir = Path(directory)
            self.load_games()
            QMessageBox.information(self, "Success", 
                                  f"Installation directory changed to:\n{directory}")
                                  
    def check_updates(self):
        """Проверить обновления лаунчера"""
        try:
            response = requests.get(self.update_url, timeout=5)
            if response.status_code == 200:
                update_info = response.json()
                latest_version = update_info.get('version')
                
                if self.compare_versions(self.launcher_version, latest_version) < 0:
                    self.prompt_update(update_info)
                else:
                    QMessageBox.information(self, "Updates", 
                                          "🎉 You have the latest version!")
            else:
                QMessageBox.warning(self, "Update Error", 
                                  "Failed to check for updates")
        except Exception as e:
            QMessageBox.critical(self, "Update Error", 
                               f"Error checking updates:\n{str(e)}")
                               
    def compare_versions(self, v1: str, v2: str) -> int:
        """Сравнить версии"""
        v1_parts = list(map(int, v1.split('.')))
        v2_parts = list(map(int, v2.split('.')))
        
        for a, b in zip(v1_parts, v2_parts):
            if a < b:
                return -1
            elif a > b:
                return 1
        return 0
        
    def prompt_update(self, update_info: Dict):
        """Предложить обновление"""
        latest_version = update_info.get('version', 'Unknown')
        changes = update_info.get('changelog', 'No changelog available')
        
        message = (
            f"🎉 New version {latest_version} is available!\n\n"
            f"Current version: {self.launcher_version}\n\n"
            f"Changes:\n{changes}\n\n"
            "Do you want to update now?"
        )
        
        reply = QMessageBox.question(
            self, "Update Available", message,
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.perform_update(update_info)
            
    def perform_update(self, update_info: Dict):
        """Выполнить обновление"""
        download_url = update_info.get('download_url')
        if not download_url:
            QMessageBox.warning(self, "Update Error", "No download URL provided")
            return
            
        try:
            # Скачиваем обновление
            response = requests.get(download_url, stream=True, timeout=30)
            
            temp_file = Path("launcher_update.exe")
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
            # Проверяем хеш
            expected_hash = update_info.get('checksum')
            if expected_hash:
                if not self.verify_file_hash(temp_file, expected_hash):
                    temp_file.unlink()
                    QMessageBox.critical(self, "Update Error", 
                                       "Checksum verification failed!")
                    return
                    
            # Запускаем процесс обновления
            self.create_update_script(temp_file)
            
            QMessageBox.information(self, "Update", 
                                  "Update downloaded! Launcher will restart to apply update.")
            self.close()
            
        except Exception as e:
            QMessageBox.critical(self, "Update Error", 
                               f"Update failed:\n{str(e)}")
                               
    def verify_file_hash(self, file_path: Path, expected_hash: str) -> bool:
        """Проверить хеш файла"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest() == expected_hash
        
    def create_update_script(self, new_launcher: Path):
        """Создать скрипт обновления"""
        current_exe = Path(sys.argv[0]).absolute()
        
        bat_content = f"""@echo off
echo Updating Pintuxx Game Launcher...
timeout /t 2 /nobreak >nul

:wait
tasklist /fi "imagename eq {current_exe.name}" | find "{current_exe.name}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)

copy /Y "{new_launcher.absolute()}" "{current_exe}" >nul
start "" "{current_exe}"
del "{new_launcher.absolute()}" >nul
del "%~f0" >nul
"""
        
        with open("update.bat", 'w') as f:
            f.write(bat_content)
            
        subprocess.Popen(["update.bat"], shell=True)
        
    def show_about(self):
        """Показать информацию о программе"""
        about_text = f"""
        Pintuxx Game Launcher v{self.launcher_version}
        
        A modern game launcher built with PySide6
        
        Features:
        • Modern dark theme
        • Accurate byte-by-byte progress bars
        • Parallel downloads
        • Game installation/uninstallation
        • Automatic updates
        • Search and filter
        
        © 2025 Pintuxx Games. All rights reserved.
        GitHub: https://github.com/DEVELOPERcreatinon
        """
        
        QMessageBox.about(self, "About", about_text)
        
    def show_changelog(self):
        """Показать историю изменений"""
        changelog = f"""
        🎉 Pintuxx Game Launcher v{self.launcher_version}
        
        COMPLETE REWRITE:
        • Migrated from Tkinter to PySide6
        • Modern dark theme with smooth animations
        • Accurate byte-by-byte progress tracking
        
        NEW FEATURES:
        • Parallel downloads with progress tracking
        • Enhanced game cards with system requirements
        • Better error handling and recovery
        • Improved update system
        
        PERFORMANCE:
        • Faster loading times
        • Reduced memory usage
        • Smooth scrolling
        
        Enjoy the new experience! 🎮
        """
        
        QMessageBox.information(self, "Changelog", changelog)
        
    def show_copyright(self):
        """Показать информацию о копирайте"""
        copyright_text = """
        Copyright Notice - Pintuxx Game Launcher
        
        LAUNCHER SOFTWARE:
        © 2025 Pintuxx Games. Developed by DeveloperCreation.
        All rights reserved.
        
        THIRD-PARTY GAMES:
        • All games are property of their respective copyright holders
        • This launcher acts as a distribution platform only
        
        REMOVAL REQUESTS:
        Contact: superlohich@mail.ru
        """
        
        QMessageBox.information(self, "Copyright", copyright_text)
        
    def on_game_installed(self, game_name: str):
        """Игра установлена"""
        print(f"Game installed: {game_name}")
        
    def on_game_uninstalled(self, game_name: str):
        """Игра удалена"""
        print(f"Game uninstalled: {game_name}")

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Устанавливаем иконку
    if os.path.exists("icon.ico"):
        app.setWindowIcon(QIcon("icon.ico"))
    
    launcher = GameLauncher()
    launcher.show()
    
    sys.exit(app.exec())

