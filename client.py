#!/usr/bin/env python3
"""
Emare VS Code Asistan - İstemci (Client)
Her makinede çalışır. Sunucuya bağlanıp VS Code ayarlarını push/pull yapar.

Kurulum:
    pip install requests rich
    python client.py setup          # Sunucu bağlantısını yapılandır
    python client.py pull            # Sunucudan ayarları çek
    python client.py push            # Ayarları sunucuya gönder
    python client.py sync            # İki yönlü senkronizasyon
    python client.py status          # Durum raporu
    python client.py watch           # Otomatik izleme
    python client.py extensions sync # Eklentileri senkronize et
"""

import json
import os
import re
import hashlib
import platform
import subprocess
import shutil
import sys
import time
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ─── Sabitler ─────────────────────────────────────────────────────────────────

CLIENT_DIR = Path(__file__).parent.resolve()
CLIENT_CONFIG = CLIENT_DIR / "client_config.json"
CLIENT_LOG = CLIENT_DIR / "client.log"
BACKUP_DIR = CLIENT_DIR / "local_backups"
BACKUP_DIR.mkdir(exist_ok=True)

OS_TYPE = platform.system().lower()  # darwin, linux, windows
MACHINE_ID = platform.node() or "unknown"

console = Console() if HAS_RICH else None


# ─── Editör Yolları ──────────────────────────────────────────────────────────

EDITOR_PATHS = {
    "vscode": {
        "name": "VS Code",
        "cli": "code",
        "darwin": "~/Library/Application Support/Code/User",
        "linux": "~/.config/Code/User",
        "windows": "%APPDATA%/Code/User",
    },
    "vscode_insiders": {
        "name": "VS Code Insiders",
        "cli": "code-insiders",
        "darwin": "~/Library/Application Support/Code - Insiders/User",
        "linux": "~/.config/Code - Insiders/User",
        "windows": "%APPDATA%/Code - Insiders/User",
    },
    "vscodium": {
        "name": "VSCodium",
        "cli": "codium",
        "darwin": "~/Library/Application Support/VSCodium/User",
        "linux": "~/.config/VSCodium/User",
        "windows": "%APPDATA%/VSCodium/User",
    },
    "windsurf": {
        "name": "Windsurf",
        "cli": "windsurf",
        "darwin": "~/Library/Application Support/Windsurf/User",
        "linux": "~/.config/Windsurf/User",
        "windows": "%APPDATA%/Windsurf/User",
    },
}


# ─── Yardımcılar ─────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] [{level}] {msg}"
    print(entry)
    try:
        with open(CLIENT_LOG, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def resolve_path(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


def get_editor_path(editor_id: str) -> Optional[Path]:
    editor = EDITOR_PATHS.get(editor_id)
    if not editor:
        return None
    path = resolve_path(editor.get(OS_TYPE, editor.get("darwin", "")))
    return path if path.exists() else None


def detect_editors() -> dict:
    """Yüklü editörleri tespit et."""
    found = {}
    for eid, econf in EDITOR_PATHS.items():
        path = get_editor_path(eid)
        if path:
            has_cli = False
            try:
                subprocess.run([econf["cli"], "--version"], capture_output=True, timeout=5)
                has_cli = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            found[eid] = {"name": econf["name"], "path": path, "cli": econf["cli"], "has_cli": has_cli}
    return found


def file_hash(fp: Path) -> str:
    if not fp.exists():
        return ""
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonc(filepath: Path):
    """VS Code JSONC (yorumlu JSON) dosyasını yükle."""
    if not filepath.exists():
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    # Çok satırlı yorumları kaldır
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    # Tek satırlı yorumları kaldır
    lines = []
    for line in content.split('\n'):
        stripped = line.lstrip()
        if stripped.startswith('//'):
            continue
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
    content = re.sub(r',\s*([}\]])', r'\1', content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def load_client_config() -> dict:
    if CLIENT_CONFIG.exists():
        with open(CLIENT_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_client_config(config: dict):
    with open(CLIENT_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def merge_json(base: dict, overlay: dict, ignore_keys: list = None) -> dict:
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


def backup_local(editor_path: Path, label: str):
    """Yerel yedek al."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"{label}_{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    for fname in ["settings.json", "keybindings.json", "mcp.json"]:
        src = editor_path / fname
        if src.exists():
            shutil.copy2(src, dest / fname)
    snippets = editor_path / "snippets"
    if snippets.exists():
        shutil.copytree(snippets, dest / "snippets", dirs_exist_ok=True)
    # Max 10 yedek tut
    backups = sorted(
        [d for d in BACKUP_DIR.iterdir() if d.is_dir() and d.name.startswith(label)],
        key=lambda x: x.stat().st_mtime, reverse=True
    )
    for old in backups[10:]:
        shutil.rmtree(old)


# ─── API İstemcisi ────────────────────────────────────────────────────────────

class SyncClient:
    """Sunucu ile iletişim kuran istemci."""

    def __init__(self, config: dict = None):
        config = config or load_client_config()
        self.server_url = config.get("server_url", "").rstrip("/")
        self.api_key = config.get("api_key", "")
        self.client_id = config.get("client_id", MACHINE_ID)
        self.ignore_keys = config.get("ignore_keys", [
            "window.zoomLevel", "workbench.colorTheme",
            "workbench.iconTheme", "editor.fontSize"
        ])
        self.editors = detect_editors()

    def _headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "X-Client-ID": self.client_id,
            "Content-Type": "application/json"
        }

    def _get(self, path: str) -> requests.Response:
        url = f"{self.server_url}{path}"
        return requests.get(url, headers=self._headers(), timeout=30)

    def _put(self, path: str, data) -> requests.Response:
        url = f"{self.server_url}{path}"
        return requests.put(url, headers=self._headers(), json=data, timeout=30)

    def _post(self, path: str, data) -> requests.Response:
        url = f"{self.server_url}{path}"
        return requests.post(url, headers=self._headers(), json=data, timeout=30)

    def test_connection(self) -> bool:
        """Sunucu bağlantısını test et."""
        try:
            r = self._get("/")
            return r.status_code == 200
        except Exception as e:
            log(f"Bağlantı hatası: {e}", "ERROR")
            return False

    def get_server_hashes(self) -> dict:
        r = self._get("/sync/hashes")
        r.raise_for_status()
        return r.json()

    # ─── Pull ─────────────────────────────────────────────────────────────

    def pull(self, force: bool = False):
        """Sunucudan ayarları çek ve tüm yerel editörlere yaz."""
        log("⬇️  Pull başlıyor...")

        if not self.test_connection():
            log("Sunucuya bağlanılamadı!", "ERROR")
            return False

        # Toplu çek
        r = self._get("/sync/pull")
        r.raise_for_status()
        vault_data = r.json()

        if not vault_data:
            log("Sunucu vault'u boş!", "WARN")
            return False

        for eid, einfo in self.editors.items():
            editor_path = einfo["path"]
            log(f"  Güncelleniyor: {einfo['name']}")

            # Yerel yedek
            backup_local(editor_path, eid)

            # Settings
            if "settings" in vault_data:
                settings_file = editor_path / "settings.json"
                vault_settings = vault_data["settings"]["data"]

                if not force:
                    # Hash kontrolü - değişmediyse atla
                    server_hash = vault_data["settings"].get("hash", "")
                    local_hash = file_hash(settings_file)
                    if server_hash == local_hash:
                        log(f"    settings.json zaten güncel: {einfo['name']}")
                    else:
                        existing = load_jsonc(settings_file) or {}
                        merged = merge_json(existing, vault_settings, self.ignore_keys)
                        with open(settings_file, "w", encoding="utf-8") as f:
                            json.dump(merged, indent=4, ensure_ascii=False, fp=f)
                        log(f"    settings.json güncellendi: {einfo['name']}")
                else:
                    with open(settings_file, "w", encoding="utf-8") as f:
                        json.dump(vault_settings, indent=4, ensure_ascii=False, fp=f)
                    log(f"    settings.json üzerine yazıldı: {einfo['name']}")

            # Keybindings
            if "keybindings" in vault_data:
                kb_file = editor_path / "keybindings.json"
                with open(kb_file, "w", encoding="utf-8") as f:
                    json.dump(vault_data["keybindings"]["data"], indent=4, ensure_ascii=False, fp=f)
                log(f"    keybindings.json güncellendi: {einfo['name']}")

            # MCP
            if "mcp" in vault_data:
                mcp_file = editor_path / "mcp.json"
                vault_mcp = vault_data["mcp"]["data"]
                existing_mcp = load_jsonc(mcp_file) or {}
                merged_mcp = merge_json(existing_mcp, vault_mcp)
                with open(mcp_file, "w", encoding="utf-8") as f:
                    json.dump(merged_mcp, indent=4, ensure_ascii=False, fp=f)
                log(f"    mcp.json güncellendi: {einfo['name']}")

            # Snippets
            if "snippets" in vault_data:
                snippets_dir = editor_path / "snippets"
                snippets_dir.mkdir(exist_ok=True)
                for fname, content in vault_data["snippets"].items():
                    with open(snippets_dir / fname, "w", encoding="utf-8") as f:
                        json.dump(content, indent=4, ensure_ascii=False, fp=f)
                log(f"    snippets güncellendi: {einfo['name']}")

            # Extensions - eklenti yükleme
            if "extensions" in vault_data and einfo.get("has_cli"):
                self._sync_extensions_for_editor(eid, einfo, vault_data["extensions"])

        log("✅ Pull tamamlandı!")
        return True

    def _sync_extensions_for_editor(self, eid: str, einfo: dict, server_extensions: list):
        """Eksik eklentileri yükle."""
        cli = einfo["cli"]
        try:
            result = subprocess.run([cli, "--list-extensions"], capture_output=True, text=True, timeout=30)
            local_exts = set(e.strip() for e in result.stdout.strip().split("\n") if e.strip())
        except Exception:
            return

        missing = set(server_extensions) - local_exts
        if missing:
            log(f"    {len(missing)} eksik eklenti yüklenecek: {einfo['name']}")
            for ext_id in sorted(missing):
                try:
                    subprocess.run([cli, "--install-extension", ext_id, "--force"],
                                   capture_output=True, timeout=120)
                    log(f"      ✓ {ext_id}")
                except Exception as e:
                    log(f"      ✗ {ext_id}: {e}", "WARN")
        else:
            log(f"    Eklentiler senkron: {einfo['name']}")

    # ─── Push ─────────────────────────────────────────────────────────────

    def push(self, source_editor: str = None):
        """Yerel editör ayarlarını sunucuya gönder."""
        log("⬆️  Push başlıyor...")

        if not self.test_connection():
            log("Sunucuya bağlanılamadı!", "ERROR")
            return False

        # Kaynak editör seç (en büyük settings.json)
        source = source_editor
        if not source:
            best_size = 0
            for eid, einfo in self.editors.items():
                s = einfo["path"] / "settings.json"
                if s.exists() and s.stat().st_size > best_size:
                    best_size = s.stat().st_size
                    source = eid

        if not source or source not in self.editors:
            log("Kaynak editör bulunamadı!", "ERROR")
            return False

        einfo = self.editors[source]
        editor_path = einfo["path"]
        log(f"  Kaynak: {einfo['name']}")

        push_data = {}

        # Settings
        settings_file = editor_path / "settings.json"
        if settings_file.exists():
            settings = load_jsonc(settings_file)
            if settings:
                push_data["settings"] = settings

        # Keybindings
        kb_file = editor_path / "keybindings.json"
        if kb_file.exists():
            kb = load_jsonc(kb_file)
            if kb is not None:
                push_data["keybindings"] = kb

        # MCP
        mcp_file = editor_path / "mcp.json"
        if mcp_file.exists():
            mcp = load_jsonc(mcp_file)
            if mcp:
                push_data["mcp"] = mcp

        # Snippets
        snippets_dir = editor_path / "snippets"
        if snippets_dir.exists():
            snippets = {}
            for fp in snippets_dir.iterdir():
                if fp.is_file() and fp.suffix == ".json":
                    with open(fp, "r", encoding="utf-8") as f:
                        try:
                            snippets[fp.name] = json.load(f)
                        except json.JSONDecodeError:
                            pass
            if snippets:
                push_data["snippets"] = snippets

        # Extensions
        if einfo.get("has_cli"):
            try:
                result = subprocess.run([einfo["cli"], "--list-extensions"],
                                       capture_output=True, text=True, timeout=30)
                exts = [e.strip() for e in result.stdout.strip().split("\n") if e.strip()]
                if exts:
                    push_data["extensions"] = exts
                    push_data["editor"] = einfo["name"]
            except Exception:
                pass

        if not push_data:
            log("Gönderilecek veri yok!", "WARN")
            return False

        # Toplu gönder
        r = self._post("/sync/push", push_data)
        r.raise_for_status()
        result = r.json()
        log(f"✅ Push tamamlandı! Gönderilen: {result.get('pushed', [])}")
        return True

    # ─── Sync ─────────────────────────────────────────────────────────────

    def sync(self, source_editor: str = None):
        """İki yönlü: önce push, sonra pull."""
        log("🔄 Tam senkronizasyon başlıyor...")
        self.push(source_editor)
        self.pull()
        log("🔄 Tam senkronizasyon tamamlandı!")

    # ─── Status ───────────────────────────────────────────────────────────

    def status(self):
        """Durum raporu."""
        editors = self.editors

        if HAS_RICH:
            # Bağlantı
            connected = self.test_connection()
            conn_panel = Panel(
                f"[bold green]✅ Bağlı[/bold green]" if connected else "[bold red]❌ Bağlantı Yok[/bold red]",
                title=f"🌐 Sunucu: {self.server_url}",
                border_style="green" if connected else "red"
            )
            console.print(conn_panel)

            # Editörler
            table = Table(title="🖥️  Yerel Editörler", box=box.ROUNDED, border_style="cyan")
            table.add_column("Editör", style="bold")
            table.add_column("Yol", style="dim")
            table.add_column("CLI", justify="center")
            table.add_column("Settings", justify="center")

            for eid, einfo in editors.items():
                s = einfo["path"] / "settings.json"
                table.add_row(
                    einfo["name"], str(einfo["path"]),
                    "✅" if einfo["has_cli"] else "❌",
                    f"{s.stat().st_size:,}B" if s.exists() else "❌"
                )
            console.print(table)

            # Sunucu hash karşılaştırması
            if connected:
                try:
                    hashes = self.get_server_hashes()
                    diff_table = Table(title="📊 Hash Karşılaştırması", box=box.ROUNDED, border_style="yellow")
                    diff_table.add_column("Dosya", style="bold")
                    diff_table.add_column("Sunucu", style="dim")
                    diff_table.add_column("Yerel (ilk editör)", style="dim")
                    diff_table.add_column("Senkron", justify="center")

                    first_editor = next(iter(editors.values()), None)
                    for fname, server_hash in hashes.items():
                        local_h = ""
                        if first_editor:
                            local_h = file_hash(first_editor["path"] / fname)
                        synced = "✅" if server_hash == local_h else "⚠️  Farklı"
                        diff_table.add_row(fname, server_hash[:12] + "...", local_h[:12] + "..." if local_h else "—", synced)

                    console.print(diff_table)
                except Exception:
                    pass
        else:
            # Rich olmadan basit çıktı
            connected = self.test_connection()
            print(f"\nSunucu: {self.server_url} - {'Bağlı' if connected else 'Bağlantı Yok'}")
            print(f"\nYerel Editörler:")
            for eid, einfo in editors.items():
                print(f"  {einfo['name']}: {einfo['path']}")

    # ─── Watch ────────────────────────────────────────────────────────────

    def watch(self, interval: int = 300):
        """Değişiklikleri izle ve otomatik senkronize et."""
        log(f"👁️  İzleme modu başlatıldı (aralık: {interval}s)")
        running = True

        def stop(sig, frame):
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, stop)

        last_hashes = {}
        for eid, einfo in self.editors.items():
            s = einfo["path"] / "settings.json"
            last_hashes[eid] = file_hash(s)

        while running:
            changed = False
            for eid, einfo in self.editors.items():
                s = einfo["path"] / "settings.json"
                current = file_hash(s)
                if current != last_hashes.get(eid, ""):
                    log(f"🔔 Değişiklik: {einfo['name']}")
                    changed = True
                    last_hashes[eid] = current

            if changed:
                self.sync()
                for eid, einfo in self.editors.items():
                    s = einfo["path"] / "settings.json"
                    last_hashes[eid] = file_hash(s)
            else:
                ts = datetime.now().strftime("%H:%M:%S")
                log(f"  [{ts}] Değişiklik yok", "DEBUG")

            for _ in range(interval):
                if not running:
                    break
                time.sleep(1)

        log("İzleme durduruldu")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def cmd_setup():
    """İlk kurulum sihirbazı."""
    print("\n🔧 Emare VS Code Asistan - İstemci Kurulumu\n")

    config = load_client_config()

    if HAS_RICH:
        server = Prompt.ask("Sunucu adresi", default=config.get("server_url", "http://SUNUCU_IP:8585"))
        api_key = Prompt.ask("API Key", default=config.get("api_key", ""))
        client_id = Prompt.ask("İstemci adı", default=config.get("client_id", MACHINE_ID))
    else:
        server = input(f"Sunucu adresi [{config.get('server_url', 'http://SUNUCU_IP:8585')}]: ").strip()
        server = server or config.get("server_url", "http://localhost:8585")
        api_key = input(f"API Key [{config.get('api_key', '')}]: ").strip() or config.get("api_key", "")
        client_id = input(f"İstemci adı [{MACHINE_ID}]: ").strip() or MACHINE_ID

    config.update({
        "server_url": server,
        "api_key": api_key,
        "client_id": client_id,
        "ignore_keys": config.get("ignore_keys", [
            "window.zoomLevel", "workbench.colorTheme",
            "workbench.iconTheme", "editor.fontSize"
        ])
    })
    save_client_config(config)

    # Test
    client = SyncClient(config)
    if client.test_connection():
        print("\n✅ Sunucu bağlantısı başarılı!")
    else:
        print("\n❌ Sunucuya bağlanılamadı. Adresi ve API key'i kontrol edin.")

    # Editörleri göster
    editors = detect_editors()
    print(f"\n📍 Tespit edilen editörler ({len(editors)}):")
    for eid, einfo in editors.items():
        print(f"   {einfo['name']} -> {einfo['path']}")


def interactive_menu():
    """İnteraktif menü."""
    config = load_client_config()
    if not config.get("server_url"):
        print("Önce kurulum yapın: python client.py setup")
        return

    client = SyncClient(config)

    if HAS_RICH:
        console.print("\n[bold cyan]╔═══════════════════════════════════════╗[/bold cyan]")
        console.print("[bold cyan]║   🔄  Emare VS Code Asistan Client  ║[/bold cyan]")
        console.print("[bold cyan]╚═══════════════════════════════════════╝[/bold cyan]")

    while True:
        print("\n── Menü ──")
        print("  1. 📊 Durum")
        print("  2. ⬇️  Pull (Sunucudan Çek)")
        print("  3. ⬆️  Push (Sunucuya Gönder)")
        print("  4. 🔄 Tam Senkronizasyon")
        print("  5. 👁️  İzleme Modu")
        print("  6. ⚙️  Ayarlar")
        print("  0. 🚪 Çıkış")

        choice = input("\nSeçim: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            client.status()
        elif choice == "2":
            client.pull()
        elif choice == "3":
            client.push()
        elif choice == "4":
            client.sync()
        elif choice == "5":
            client.watch()
        elif choice == "6":
            cmd_setup()
            config = load_client_config()
            client = SyncClient(config)


def main():
    if len(sys.argv) < 2:
        interactive_menu()
        return

    command = sys.argv[1].lower()

    if command == "setup":
        cmd_setup()
        return

    config = load_client_config()
    if not config.get("server_url"):
        print("Önce kurulum yapın: python client.py setup")
        sys.exit(1)

    client = SyncClient(config)

    commands = {
        "status": client.status,
        "pull": lambda: client.pull(force="--force" in sys.argv),
        "push": lambda: client.push(sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "--force" else None),
        "sync": lambda: client.sync(),
        "watch": lambda: client.watch(int(sys.argv[2]) if len(sys.argv) > 2 else 300),
    }

    if command in commands:
        commands[command]()
    elif command in ("help", "--help", "-h"):
        print(__doc__)
    else:
        print(f"Bilinmeyen komut: {command}")
        print(f"Komutlar: {', '.join(commands.keys())}")


if __name__ == "__main__":
    main()
