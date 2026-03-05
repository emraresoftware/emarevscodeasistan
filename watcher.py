#!/usr/bin/env python3
"""
Emare VS Code Asistan - File Watcher
Dosya değişikliklerini watchdog ile izler ve otomatik senkronize eder.
"""

import time
import sys
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from sync_engine import SyncEngine, log, file_hash


class VSCodeSettingsHandler(FileSystemEventHandler):
    """VS Code ayar dosyası değişiklik izleyicisi."""

    WATCH_FILES = {"settings.json", "keybindings.json", "mcp.json"}
    WATCH_DIRS = {"snippets"}

    def __init__(self, engine: SyncEngine):
        self.engine = engine
        self.last_sync = 0
        self.cooldown = 5  # 5 saniye cooldown

    def on_modified(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)

        # Ayar dosyası mı?
        if path.name in self.WATCH_FILES or path.parent.name in self.WATCH_DIRS:
            now = time.time()
            if now - self.last_sync < self.cooldown:
                return

            self.last_sync = now
            log(f"🔔 Değişiklik: {path}")

            # Hangi editörün değiştiğini bul
            for eid, einfo in self.engine.editors.items():
                editor_path = str(einfo["path"])
                if str(path).startswith(editor_path):
                    log(f"Kaynak editör: {einfo['name']}")
                    self.engine.pull(eid)
                    self.engine.push([e for e in self.engine.editors if e != eid])
                    log("✅ Otomatik senkronizasyon tamamlandı")
                    return


def start_watcher():
    """Dosya izleyiciyi başlat."""
    engine = SyncEngine()
    handler = VSCodeSettingsHandler(engine)
    observer = Observer()

    for eid, einfo in engine.editors.items():
        path = str(einfo["path"])
        observer.schedule(handler, path, recursive=True)
        log(f"İzleniyor: {einfo['name']} -> {path}")

    observer.start()
    log("👁️  File watcher başlatıldı (Ctrl+C ile durdurun)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        log("File watcher durduruldu")

    observer.join()


if __name__ == "__main__":
    start_watcher()
