#!/usr/bin/env python3
"""
Emare VS Code Asistan - Senkronizasyon Motoru
Tüm VS Code kurulumlarının ayarlarını merkezi olarak senkronize eder.

Desteklenen editörler: VS Code, VS Code Insiders, Cursor, VSCodium, Windsurf
Senkronize edilen öğeler: settings.json, keybindings.json, snippets, mcp.json,
                          eklenti listesi, profiller, workspace ayarları
"""

import json
import os
import shutil
import hashlib
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# ─── Sabitler ─────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = BASE_DIR / "config.json"
VAULT_DIR = BASE_DIR / "vault"
BACKUP_DIR = BASE_DIR / "backups"
LOG_FILE = BASE_DIR / "sync.log"
STATE_FILE = BASE_DIR / "state.json"
LOCK_FILE = BASE_DIR / ".sync.lock"

OS_TYPE = platform.system().lower()  # darwin, linux, windows


# ─── Yardımcı Fonksiyonlar ───────────────────────────────────────────────────

def log(message: str, level: str = "INFO"):
    """Loglama - hem dosyaya hem konsola."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{level}] {message}"
    print(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def load_config() -> dict:
    """config.json dosyasını yükle."""
    if not CONFIG_FILE.exists():
        log("config.json bulunamadı!", "ERROR")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    """Son senkronizasyon durumunu yükle."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_sync": None, "synced_editors": {}, "hashes": {}}


def save_state(state: dict):
    """Durumu kaydet."""
    state["last_sync"] = datetime.now().isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def resolve_path(path_str: str) -> Path:
    """Platform bağımsız yol çözümlemesi."""
    path_str = os.path.expanduser(path_str)
    path_str = os.path.expandvars(path_str)
    return Path(path_str)


def get_editor_config_path(editor_config: dict) -> Optional[Path]:
    """Editör yapılandırma yolunu platform bazlı çözümle."""
    platform_key = {
        "darwin": "mac",
        "linux": "linux",
        "windows": "windows"
    }.get(OS_TYPE, "mac")

    path_str = editor_config.get(platform_key, editor_config.get("config_path", ""))
    path = resolve_path(path_str)

    if path.exists():
        return path
    return None


def file_hash(filepath: Path) -> str:
    """Dosyanın SHA256 hash'ini hesapla."""
    if not filepath.exists():
        return ""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_hash(dirpath: Path) -> str:
    """Klasörün bileşik hash'ini hesapla."""
    if not dirpath.exists():
        return ""
    h = hashlib.sha256()
    for fp in sorted(dirpath.rglob("*")):
        if fp.is_file():
            h.update(str(fp.relative_to(dirpath)).encode())
            h.update(file_hash(fp).encode())
    return h.hexdigest()


def merge_json(base: dict, overlay: dict, ignore_keys: list = None) -> dict:
    """İki JSON objesini akıllıca birleştir."""
    ignore_keys = ignore_keys or []
    merged = base.copy()
    for key, value in overlay.items():
        if key in ignore_keys:
            continue
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_json(merged[key], value, ignore_keys)
        else:
            merged[key] = value
    return merged


def pretty_json(data: dict) -> str:
    """JSON'u güzel formatlı string'e dönüştür."""
    return json.dumps(data, indent=4, ensure_ascii=False, sort_keys=False)


def load_jsonc(filepath: Path):
    """JSONC (yorumlu JSON) dosyasını yükle - VS Code formatı."""
    if not filepath.exists():
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    # Tek satır yorumları kaldır (string içindekiler hariç)
    import re
    # Çok satırlı yorumları kaldır
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    # Tek satırlı yorumları kaldır (sadece satır başında veya boşluktan sonra)
    lines = []
    for line in content.split('\n'):
        stripped = line.lstrip()
        if stripped.startswith('//'):
            continue
        # Satır içi // yorumları (string dışında)
        in_string = False
        escape = False
        result = []
        i = 0
        while i < len(line):
            c = line[i]
            if escape:
                result.append(c)
                escape = False
                i += 1
                continue
            if c == '\\' and in_string:
                result.append(c)
                escape = True
                i += 1
                continue
            if c == '"':
                in_string = not in_string
            if not in_string and i + 1 < len(line) and line[i:i+2] == '//':
                break
            result.append(c)
            i += 1
        lines.append(''.join(result))
    content = '\n'.join(lines)
    # Trailing comma'ları kaldır (JSON'da geçersiz)
    content = re.sub(r',\s*([}\]])', r'\1', content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        log(f"JSONC parse hatası ({filepath.name}): {e}", "WARN")
        return None


# ─── Backup Sistemi ──────────────────────────────────────────────────────────

class BackupManager:
    """Yedekleme yöneticisi."""

    def __init__(self, config: dict):
        self.backup_dir = resolve_path(config.get("backup_dir", "backups"))
        if not self.backup_dir.is_absolute():
            self.backup_dir = BASE_DIR / self.backup_dir
        self.max_backups = config.get("max_backups", 10)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def backup(self, editor_name: str, source_path: Path) -> Path:
        """Bir editörün ayarlarını yedekle."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = editor_name.replace(" ", "_").lower()
        backup_path = self.backup_dir / f"{safe_name}_{timestamp}"
        backup_path.mkdir(parents=True, exist_ok=True)

        if source_path.is_dir():
            for item in source_path.iterdir():
                if item.name.startswith("."):
                    continue
                dest = backup_path / item.name
                if item.is_file():
                    shutil.copy2(item, dest)
                elif item.is_dir() and item.name in ("snippets", "profiles"):
                    shutil.copytree(item, dest, dirs_exist_ok=True)

        log(f"Yedek oluşturuldu: {backup_path}", "BACKUP")
        self._cleanup(safe_name)
        return backup_path

    def _cleanup(self, editor_prefix: str):
        """Eski yedekleri temizle."""
        backups = sorted(
            [d for d in self.backup_dir.iterdir()
             if d.is_dir() and d.name.startswith(editor_prefix)],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        for old_backup in backups[self.max_backups:]:
            shutil.rmtree(old_backup)
            log(f"Eski yedek silindi: {old_backup.name}", "CLEANUP")

    def list_backups(self) -> list:
        """Tüm yedekleri listele."""
        backups = []
        for d in sorted(self.backup_dir.iterdir(), reverse=True):
            if d.is_dir():
                backups.append({
                    "name": d.name,
                    "path": str(d),
                    "date": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
                    "size": sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                })
        return backups

    def restore(self, backup_name: str, target_path: Path) -> bool:
        """Bir yedeği geri yükle."""
        backup_path = self.backup_dir / backup_name
        if not backup_path.exists():
            log(f"Yedek bulunamadı: {backup_name}", "ERROR")
            return False

        for item in backup_path.iterdir():
            dest = target_path / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            elif item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)

        log(f"Yedek geri yüklendi: {backup_name} -> {target_path}", "RESTORE")
        return True


# ─── Vault (Merkezi Depo) ────────────────────────────────────────────────────

class Vault:
    """Merkezi ayar deposu - tüm ayarların 'doğru' kopyası burada tutulur."""

    def __init__(self, config: dict):
        self.vault_dir = resolve_path(config.get("vault_dir", "vault"))
        if not self.vault_dir.is_absolute():
            self.vault_dir = BASE_DIR / self.vault_dir
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.ignore_keys = config.get("ignore_keys", [])

        # Alt dizinleri oluştur
        (self.vault_dir / "snippets").mkdir(exist_ok=True)
        (self.vault_dir / "profiles").mkdir(exist_ok=True)
        (self.vault_dir / "extensions").mkdir(exist_ok=True)
        (self.vault_dir / "workspaces").mkdir(exist_ok=True)

    @property
    def settings_file(self) -> Path:
        return self.vault_dir / "settings.json"

    @property
    def keybindings_file(self) -> Path:
        return self.vault_dir / "keybindings.json"

    @property
    def mcp_file(self) -> Path:
        return self.vault_dir / "mcp.json"

    @property
    def snippets_dir(self) -> Path:
        return self.vault_dir / "snippets"

    @property
    def profiles_dir(self) -> Path:
        return self.vault_dir / "profiles"

    @property
    def extensions_dir(self) -> Path:
        return self.vault_dir / "extensions"

    def save_settings(self, data: dict):
        """Ayarları vault'a kaydet."""
        with open(self.settings_file, "w", encoding="utf-8") as f:
            f.write(pretty_json(data))
        log("Vault: settings.json güncellendi")

    def load_settings(self) -> dict:
        """Vault'tan ayarları yükle."""
        if self.settings_file.exists():
            with open(self.settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_keybindings(self, data: list):
        """Kısayolları vault'a kaydet."""
        with open(self.keybindings_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=4, ensure_ascii=False))
        log("Vault: keybindings.json güncellendi")

    def load_keybindings(self) -> list:
        if self.keybindings_file.exists():
            with open(self.keybindings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def save_mcp(self, data: dict):
        """MCP ayarlarını vault'a kaydet."""
        with open(self.mcp_file, "w", encoding="utf-8") as f:
            f.write(pretty_json(data))
        log("Vault: mcp.json güncellendi")

    def load_mcp(self) -> dict:
        if self.mcp_file.exists():
            with open(self.mcp_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_snippets(self, source_dir: Path):
        """Snippet'leri vault'a kopyala."""
        if source_dir.exists() and source_dir.is_dir():
            for item in source_dir.iterdir():
                if item.is_file() and item.suffix == ".json":
                    shutil.copy2(item, self.snippets_dir / item.name)
            log("Vault: snippets güncellendi")

    def save_extension_list(self, editor_name: str, extensions: list):
        """Eklenti listesini vault'a kaydet."""
        safe = editor_name.replace(" ", "_").lower()
        filepath = self.extensions_dir / f"{safe}_extensions.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"editor": editor_name, "extensions": extensions,
                       "updated": datetime.now().isoformat()}, f, indent=2)
        log(f"Vault: {editor_name} eklenti listesi kaydedildi ({len(extensions)} eklenti)")

    def load_extension_list(self, editor_name: str) -> list:
        safe = editor_name.replace(" ", "_").lower()
        filepath = self.extensions_dir / f"{safe}_extensions.json"
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f).get("extensions", [])
        return []

    def get_master_extensions(self) -> set:
        """Tüm editörlerden birleştirilmiş eklenti listesi."""
        all_ext = set()
        for fp in self.extensions_dir.glob("*_extensions.json"):
            with open(fp, "r", encoding="utf-8") as f:
                exts = json.load(f).get("extensions", [])
                all_ext.update(exts)
        return all_ext


# ─── Eklenti Yönetimi ────────────────────────────────────────────────────────

class ExtensionManager:
    """Eklenti yükleme/listeleme yöneticisi."""

    CLI_COMMANDS = {
        "vscode": "code",
        "vscode_insiders": "code-insiders",
        "cursor": "cursor",
        "vscodium": "codium",
        "windsurf": "windsurf",
    }

    @staticmethod
    def get_cli(editor_id: str) -> Optional[str]:
        """Editörün CLI komutunu döndür."""
        cmd = ExtensionManager.CLI_COMMANDS.get(editor_id)
        if cmd:
            try:
                subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
                return cmd
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return None
        return None

    @staticmethod
    def list_extensions(editor_id: str) -> list:
        """Editöre yüklü eklentileri listele."""
        cli = ExtensionManager.get_cli(editor_id)
        if not cli:
            # CLI yoksa, extensions.json dosyasından oku
            return ExtensionManager._list_from_profile(editor_id)
        try:
            result = subprocess.run(
                [cli, "--list-extensions"],
                capture_output=True, text=True, timeout=30
            )
            return [e.strip() for e in result.stdout.strip().split("\n") if e.strip()]
        except Exception as e:
            log(f"Eklenti listesi alınamadı ({editor_id}): {e}", "WARN")
            return []

    @staticmethod
    def _list_from_profile(editor_id: str) -> list:
        """Profile klasöründeki extensions.json'dan eklenti listesi çıkar."""
        config = load_config()
        editor_conf = config.get("editors", {}).get(editor_id, {})
        config_path = get_editor_config_path(editor_conf)
        if not config_path:
            return []

        extensions = []
        profiles_dir = config_path / "profiles"
        if profiles_dir.exists():
            for profile_dir in profiles_dir.iterdir():
                ext_file = profile_dir / "extensions.json"
                if ext_file.exists():
                    try:
                        with open(ext_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            for ext in data:
                                ext_id = ext.get("identifier", {}).get("id", "")
                                if ext_id and ext_id not in extensions:
                                    extensions.append(ext_id)
                    except Exception:
                        pass
        return extensions

    @staticmethod
    def install_extension(editor_id: str, extension_id: str) -> bool:
        """Eklentiyi yükle."""
        cli = ExtensionManager.get_cli(editor_id)
        if not cli:
            log(f"CLI bulunamadı ({editor_id}), eklenti yüklenemedi: {extension_id}", "WARN")
            return False
        try:
            result = subprocess.run(
                [cli, "--install-extension", extension_id, "--force"],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                log(f"Eklenti yüklendi: {extension_id} -> {editor_id}")
                return True
            else:
                log(f"Eklenti yüklenemedi: {extension_id} -> {editor_id}: {result.stderr}", "WARN")
                return False
        except Exception as e:
            log(f"Eklenti yükleme hatası: {e}", "ERROR")
            return False

    @staticmethod
    def sync_extensions(source_editor: str, target_editors: list, vault: Vault):
        """Eklentileri kaynaktan hedeflere senkronize et."""
        source_exts = set(ExtensionManager.list_extensions(source_editor))
        vault.save_extension_list(source_editor, list(source_exts))

        for target_id in target_editors:
            if target_id == source_editor:
                continue
            target_exts = set(ExtensionManager.list_extensions(target_id))
            missing = source_exts - target_exts
            if missing:
                log(f"{len(missing)} eksik eklenti bulundu: {source_editor} -> {target_id}")
                for ext_id in sorted(missing):
                    ExtensionManager.install_extension(target_id, ext_id)
            else:
                log(f"Tüm eklentiler senkron: {target_id}")


# ─── Workspace Senkronizasyonu ───────────────────────────────────────────────

class WorkspaceSyncer:
    """Emare workspace'lerinin .vscode ayarlarını senkronize eder."""

    def __init__(self, config: dict, vault: Vault):
        self.config = config.get("workspace_sync", {})
        self.vault = vault
        self.emare_root = Path(self.config.get("emare_root", "/Users/emre/Desktop/Emare"))
        self.workspace_vault = vault.vault_dir / "workspaces"
        self.workspace_vault.mkdir(parents=True, exist_ok=True)

    def discover_workspaces(self) -> list:
        """Emare altındaki tüm .vscode klasörlerini bul."""
        workspaces = []
        if not self.emare_root.exists():
            return workspaces

        for item in self.emare_root.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                vscode_dir = item / ".vscode"
                if vscode_dir.exists():
                    workspaces.append({
                        "name": item.name,
                        "path": str(item),
                        "vscode_dir": str(vscode_dir),
                        "files": [f.name for f in vscode_dir.iterdir() if f.is_file()]
                    })
        return workspaces

    def collect_workspace_settings(self) -> dict:
        """Tüm workspace'lerin .vscode ayarlarını topla."""
        workspaces = self.discover_workspaces()
        collected = {}
        for ws in workspaces:
            ws_vault = self.workspace_vault / ws["name"]
            ws_vault.mkdir(exist_ok=True)
            vscode_dir = Path(ws["vscode_dir"])

            for fname in ["settings.json", "launch.json", "tasks.json", "extensions.json"]:
                src = vscode_dir / fname
                if src.exists():
                    shutil.copy2(src, ws_vault / fname)

            collected[ws["name"]] = ws
        return collected

    def distribute_settings(self, template: dict, target_projects: list = None):
        """Ortak workspace ayarlarını projelere dağıt."""
        workspaces = self.discover_workspaces()
        for ws in workspaces:
            if target_projects and ws["name"] not in target_projects:
                continue
            vscode_dir = Path(ws["vscode_dir"])
            settings_file = vscode_dir / "settings.json"

            existing = {}
            if settings_file.exists():
                with open(settings_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)

            merged = merge_json(existing, template)
            with open(settings_file, "w", encoding="utf-8") as f:
                f.write(pretty_json(merged))
            log(f"Workspace ayarları güncellendi: {ws['name']}")


# ─── Ana Senkronizasyon Motoru ────────────────────────────────────────────────

class SyncEngine:
    """Ana senkronizasyon motoru."""

    def __init__(self):
        self.config = load_config()
        self.state = load_state()
        self.vault = Vault(self.config)
        self.backup_mgr = BackupManager(self.config)
        self.workspace_syncer = WorkspaceSyncer(self.config, self.vault)
        self.editors = self._detect_editors()

    def _detect_editors(self) -> dict:
        """Sistemde yüklü editörleri tespit et."""
        detected = {}
        for editor_id, editor_conf in self.config.get("editors", {}).items():
            if not editor_conf.get("enabled", False):
                continue
            config_path = get_editor_config_path(editor_conf)
            if config_path:
                detected[editor_id] = {
                    "name": editor_conf["name"],
                    "path": config_path,
                    "has_cli": ExtensionManager.get_cli(editor_id) is not None,
                    "config": editor_conf
                }
                log(f"Editör bulundu: {editor_conf['name']} -> {config_path}")
            else:
                log(f"Editör bulunamadı: {editor_conf['name']}", "SKIP")
        return detected

    def get_status(self) -> dict:
        """Mevcut senkronizasyon durumunu raporla."""
        status = {
            "detected_editors": {},
            "vault_status": {},
            "last_sync": self.state.get("last_sync"),
            "workspace_count": len(self.workspace_syncer.discover_workspaces()),
            "backups": len(self.backup_mgr.list_backups())
        }

        for eid, einfo in self.editors.items():
            editor_path = einfo["path"]
            status["detected_editors"][eid] = {
                "name": einfo["name"],
                "path": str(editor_path),
                "has_cli": einfo["has_cli"],
                "settings_exists": (editor_path / "settings.json").exists(),
                "keybindings_exists": (editor_path / "keybindings.json").exists(),
                "snippets_exists": (editor_path / "snippets").exists(),
                "mcp_exists": (editor_path / "mcp.json").exists(),
                "profiles_exist": (editor_path / "profiles").exists(),
            }

        status["vault_status"] = {
            "settings": self.vault.settings_file.exists(),
            "keybindings": self.vault.keybindings_file.exists(),
            "mcp": self.vault.mcp_file.exists(),
            "snippets": any(self.vault.snippets_dir.iterdir()) if self.vault.snippets_dir.exists() else False,
        }

        return status

    def pull(self, source_editor: str = None):
        """
        Bir editörden ayarları çek ve vault'a kaydet.
        source_editor belirtilmezse en kapsamlı olanı seçer.
        """
        if source_editor and source_editor in self.editors:
            source = source_editor
        else:
            # En büyük settings.json'a sahip editörü seç
            source = self._pick_best_source()

        if not source:
            log("Hiçbir editör bulunamadı!", "ERROR")
            return False

        editor = self.editors[source]
        editor_path = editor["path"]
        log(f"Kaynak editör: {editor['name']} ({editor_path})")

        # Yedekle
        self.backup_mgr.backup(editor["name"], editor_path)

        # Settings
        settings_file = editor_path / "settings.json"
        if settings_file.exists():
            settings = load_jsonc(settings_file)
            if settings:
                self.vault.save_settings(settings)

        # Keybindings
        kb_file = editor_path / "keybindings.json"
        if kb_file.exists():
            keybindings = load_jsonc(kb_file)
            if keybindings is not None:
                self.vault.save_keybindings(keybindings)

        # MCP
        mcp_file = editor_path / "mcp.json"
        if mcp_file.exists():
            mcp = load_jsonc(mcp_file)
            if mcp:
                self.vault.save_mcp(mcp)

        # Snippets
        snippets_dir = editor_path / "snippets"
        if snippets_dir.exists():
            self.vault.save_snippets(snippets_dir)

        # Eklentiler
        extensions = ExtensionManager.list_extensions(source)
        if extensions:
            self.vault.save_extension_list(editor["name"], extensions)

        # Profiller
        profiles_dir = editor_path / "profiles"
        if profiles_dir.exists():
            vault_profiles = self.vault.profiles_dir
            for profile in profiles_dir.iterdir():
                if profile.is_dir():
                    dest = vault_profiles / profile.name
                    dest.mkdir(exist_ok=True)
                    for f in profile.iterdir():
                        if f.is_file():
                            shutil.copy2(f, dest / f.name)
            log("Profiller vault'a kopyalandı")

        self.state["synced_editors"][source] = {
            "last_pull": datetime.now().isoformat(),
            "settings_hash": file_hash(settings_file)
        }
        save_state(self.state)
        log(f"✅ Pull tamamlandı: {editor['name']}")
        return True

    def push(self, target_editors: list = None):
        """
        Vault'taki ayarları hedef editörlere dağıt.
        target_editors belirtilmezse tüm aktif editörlere dağıtır.
        """
        if not self.vault.settings_file.exists():
            log("Vault boş! Önce 'pull' komutu çalıştırın.", "ERROR")
            return False

        targets = target_editors or list(self.editors.keys())
        vault_settings = self.vault.load_settings()
        vault_keybindings = self.vault.load_keybindings()
        vault_mcp = self.vault.load_mcp()
        ignore_keys = self.config.get("ignore_keys", [])

        for editor_id in targets:
            if editor_id not in self.editors:
                log(f"Editör bulunamadı: {editor_id}", "SKIP")
                continue

            editor = self.editors[editor_id]
            editor_path = editor["path"]
            log(f"Push başlıyor: {editor['name']}")

            # Yedekle
            self.backup_mgr.backup(editor["name"], editor_path)

            # Settings - akıllı birleştirme
            settings_file = editor_path / "settings.json"
            if vault_settings:
                existing = {}
                if settings_file.exists():
                    existing = load_jsonc(settings_file) or {}
                merged = merge_json(existing, vault_settings, ignore_keys)
                with open(settings_file, "w", encoding="utf-8") as f:
                    f.write(pretty_json(merged))
                log(f"  settings.json güncellendi: {editor['name']}")

            # Keybindings
            kb_file = editor_path / "keybindings.json"
            if vault_keybindings:
                with open(kb_file, "w", encoding="utf-8") as f:
                    f.write(json.dumps(vault_keybindings, indent=4, ensure_ascii=False))
                log(f"  keybindings.json güncellendi: {editor['name']}")

            # MCP
            mcp_file = editor_path / "mcp.json"
            if vault_mcp:
                existing_mcp = {}
                if mcp_file.exists():
                    existing_mcp = load_jsonc(mcp_file) or {}
                merged_mcp = merge_json(existing_mcp, vault_mcp)
                with open(mcp_file, "w", encoding="utf-8") as f:
                    f.write(pretty_json(merged_mcp))
                log(f"  mcp.json güncellendi: {editor['name']}")

            # Snippets
            vault_snippets = self.vault.snippets_dir
            if any(vault_snippets.iterdir()):
                target_snippets = editor_path / "snippets"
                target_snippets.mkdir(exist_ok=True)
                for snippet_file in vault_snippets.iterdir():
                    if snippet_file.is_file():
                        shutil.copy2(snippet_file, target_snippets / snippet_file.name)
                log(f"  snippets güncellendi: {editor['name']}")

            self.state["synced_editors"][editor_id] = {
                "last_push": datetime.now().isoformat(),
                "settings_hash": file_hash(settings_file)
            }

        save_state(self.state)
        log("✅ Push tamamlandı!")
        return True

    def sync(self, source: str = None):
        """Tam senkronizasyon: pull + push."""
        log("═══ Tam Senkronizasyon Başlıyor ═══")
        if self.pull(source):
            self.push()
            # Workspace ayarlarını da senkronize et
            if self.config.get("workspace_sync", {}).get("enabled", False):
                self.workspace_syncer.collect_workspace_settings()
                log("Workspace ayarları toplandı")
        log("═══ Senkronizasyon Tamamlandı ═══")

    def sync_extensions_all(self):
        """Tüm editörlerdeki eklentileri senkronize et."""
        editor_ids = list(self.editors.keys())
        if not editor_ids:
            log("Hiçbir editör bulunamadı!", "ERROR")
            return

        # En çok eklentiye sahip editörü kaynak olarak belirle
        best_source = None
        max_count = 0
        for eid in editor_ids:
            exts = ExtensionManager.list_extensions(eid)
            if len(exts) > max_count:
                max_count = len(exts)
                best_source = eid

        if best_source:
            ExtensionManager.sync_extensions(best_source, editor_ids, self.vault)

    def diff(self) -> dict:
        """Editörler arasındaki farkları raporla."""
        diffs = {}
        vault_settings = self.vault.load_settings()

        for eid, einfo in self.editors.items():
            editor_path = einfo["path"]
            settings_file = editor_path / "settings.json"
            if not settings_file.exists():
                continue

            with open(settings_file, "r", encoding="utf-8") as f:
                editor_settings = json.load(f)

            # Farkları bul
            only_in_vault = set(vault_settings.keys()) - set(editor_settings.keys())
            only_in_editor = set(editor_settings.keys()) - set(vault_settings.keys())
            different_values = []
            for key in set(vault_settings.keys()) & set(editor_settings.keys()):
                if vault_settings[key] != editor_settings[key]:
                    different_values.append(key)

            diffs[eid] = {
                "name": einfo["name"],
                "only_in_vault": list(only_in_vault),
                "only_in_editor": list(only_in_editor),
                "different_values": different_values,
                "total_diff": len(only_in_vault) + len(only_in_editor) + len(different_values)
            }

        return diffs

    def _pick_best_source(self) -> Optional[str]:
        """En kapsamlı ayarlara sahip editörü seç."""
        best = None
        best_size = 0
        for eid, einfo in self.editors.items():
            settings = einfo["path"] / "settings.json"
            if settings.exists():
                size = settings.stat().st_size
                if size > best_size:
                    best_size = size
                    best = eid
        return best


# ─── Modül test / standalone kullanım ────────────────────────────────────────

if __name__ == "__main__":
    # Basit test
    engine = SyncEngine()
    status = engine.get_status()
    print(json.dumps(status, indent=2, ensure_ascii=False, default=str))
