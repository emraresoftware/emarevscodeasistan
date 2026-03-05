#!/usr/bin/env python3
"""
Emare VS Code Asistan - CLI Arayüzü
Rich tabanlı interaktif terminal arayüzü.

Kullanım:
    python cli.py status          # Durum raporu
    python cli.py pull [editor]   # Editörden ayarları çek
    python cli.py push [editor]   # Ayarları editörlere dağıt
    python cli.py sync            # Tam senkronizasyon
    python cli.py diff            # Farkları göster
    python cli.py extensions      # Eklenti senkronizasyonu
    python cli.py backups         # Yedekleri listele
    python cli.py restore <name>  # Yedeği geri yükle
    python cli.py workspaces      # Workspace'leri listele
    python cli.py watch           # Otomatik izleme modu
"""

import sys
import json
import time
import signal
from pathlib import Path
from datetime import datetime

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.tree import Tree
    from rich.live import Live
    from rich.layout import Layout
    from rich.text import Text
    from rich.prompt import Prompt, Confirm
    from rich import box
except ImportError:
    print("Rich kütüphanesi gerekli: pip install rich")
    sys.exit(1)

from sync_engine import SyncEngine, ExtensionManager, log

console = Console()

# ─── Banner ──────────────────────────────────────────────────────────────────

BANNER = """
[bold cyan]╔═══════════════════════════════════════════════╗
║     🔄  Emare VS Code Asistan  🔄            ║
║   Tüm VS Code Ayarlarını Senkronize Et       ║
╚═══════════════════════════════════════════════╝[/bold cyan]
"""


def show_banner():
    console.print(BANNER)


# ─── Status Komutu ───────────────────────────────────────────────────────────

def cmd_status(engine: SyncEngine):
    """Durum raporunu göster."""
    status = engine.get_status()

    # Editörler Tablosu
    table = Table(
        title="🖥️  Tespit Edilen Editörler",
        box=box.ROUNDED,
        border_style="cyan",
        header_style="bold magenta"
    )
    table.add_column("Editör", style="bold white")
    table.add_column("Yol", style="dim")
    table.add_column("CLI", justify="center")
    table.add_column("Settings", justify="center")
    table.add_column("Keybindings", justify="center")
    table.add_column("Snippets", justify="center")
    table.add_column("MCP", justify="center")
    table.add_column("Profiller", justify="center")

    for eid, edata in status["detected_editors"].items():
        table.add_row(
            edata["name"],
            str(Path(edata["path"]).name),
            "✅" if edata["has_cli"] else "❌",
            "✅" if edata["settings_exists"] else "❌",
            "✅" if edata["keybindings_exists"] else "❌",
            "✅" if edata["snippets_exists"] else "❌",
            "✅" if edata["mcp_exists"] else "❌",
            "✅" if edata["profiles_exist"] else "❌",
        )

    console.print(table)

    # Vault Durumu
    vault_table = Table(
        title="🏦  Vault (Merkezi Depo) Durumu",
        box=box.ROUNDED,
        border_style="green"
    )
    vault_table.add_column("Öğe", style="bold")
    vault_table.add_column("Durum", justify="center")

    vault = status["vault_status"]
    vault_table.add_row("settings.json", "✅ Mevcut" if vault.get("settings") else "⚪ Boş")
    vault_table.add_row("keybindings.json", "✅ Mevcut" if vault.get("keybindings") else "⚪ Boş")
    vault_table.add_row("mcp.json", "✅ Mevcut" if vault.get("mcp") else "⚪ Boş")
    vault_table.add_row("snippets", "✅ Mevcut" if vault.get("snippets") else "⚪ Boş")

    console.print(vault_table)

    # Genel bilgiler
    info = Table.grid(padding=1)
    info.add_column(style="bold cyan")
    info.add_column()
    info.add_row("Son Senkronizasyon:", status.get("last_sync") or "Henüz yapılmadı")
    info.add_row("Workspace Sayısı:", str(status.get("workspace_count", 0)))
    info.add_row("Yedek Sayısı:", str(status.get("backups", 0)))

    console.print(Panel(info, title="📊 Genel Bilgiler", border_style="yellow"))


# ─── Pull Komutu ─────────────────────────────────────────────────────────────

def cmd_pull(engine: SyncEngine, editor: str = None):
    """Editörden ayarları çek."""
    if not engine.editors:
        console.print("[red]Hiçbir editör tespit edilemedi![/red]")
        return

    if editor and editor not in engine.editors:
        console.print(f"[red]Editör bulunamadı: {editor}[/red]")
        console.print(f"Kullanılabilir editörler: {', '.join(engine.editors.keys())}")
        return

    if not editor:
        # Editör seçimi
        console.print("\n[bold]Kaynak editör seçin:[/bold]")
        editors_list = list(engine.editors.items())
        for i, (eid, einfo) in enumerate(editors_list, 1):
            settings = einfo["path"] / "settings.json"
            size = f"({settings.stat().st_size:,} bytes)" if settings.exists() else "(boş)"
            console.print(f"  [cyan]{i}[/cyan]. {einfo['name']} {size}")

        choice = Prompt.ask(
            "Seçiminiz",
            choices=[str(i) for i in range(1, len(editors_list) + 1)],
            default="1"
        )
        editor = editors_list[int(choice) - 1][0]

    with console.status(f"[bold green]{engine.editors[editor]['name']} ayarları çekiliyor..."):
        success = engine.pull(editor)

    if success:
        console.print(f"\n[bold green]✅ Ayarlar çekildi: {engine.editors[editor]['name']} -> Vault[/bold green]")
    else:
        console.print("\n[bold red]❌ Pull başarısız![/bold red]")


# ─── Push Komutu ─────────────────────────────────────────────────────────────

def cmd_push(engine: SyncEngine, target: str = None):
    """Ayarları editörlere dağıt."""
    if not engine.vault.settings_file.exists():
        console.print("[red]Vault boş! Önce 'pull' komutu çalıştırın.[/red]")
        return

    targets = [target] if target else None

    if target and target not in engine.editors:
        console.print(f"[red]Editör bulunamadı: {target}[/red]")
        return

    target_names = [engine.editors[t]["name"] for t in (targets or engine.editors.keys()) if t in engine.editors]
    console.print(f"\n[bold]Hedef editörler:[/bold] {', '.join(target_names)}")

    if not Confirm.ask("Devam edilsin mi?", default=True):
        return

    with console.status("[bold green]Ayarlar dağıtılıyor..."):
        success = engine.push(targets)

    if success:
        console.print("\n[bold green]✅ Push tamamlandı![/bold green]")
    else:
        console.print("\n[bold red]❌ Push başarısız![/bold red]")


# ─── Sync Komutu ─────────────────────────────────────────────────────────────

def cmd_sync(engine: SyncEngine):
    """Tam senkronizasyon."""
    console.print("\n[bold yellow]🔄 Tam senkronizasyon başlıyor...[/bold yellow]\n")

    if not engine.editors:
        console.print("[red]Hiçbir editör tespit edilemedi![/red]")
        return

    # Kaynak seçimi
    console.print("[bold]Kaynak editör (en büyük ayar dosyası olan):[/bold]")
    best = engine._pick_best_source()
    if best:
        console.print(f"  → {engine.editors[best]['name']}")

    if not Confirm.ask("\nDevam edilsin mi?", default=True):
        return

    engine.sync(best)
    console.print("\n[bold green]✅ Tam senkronizasyon tamamlandı![/bold green]")


# ─── Diff Komutu ─────────────────────────────────────────────────────────────

def cmd_diff(engine: SyncEngine):
    """Editörler arasındaki farkları göster."""
    if not engine.vault.settings_file.exists():
        console.print("[yellow]Vault boş. Önce 'pull' çalıştırın.[/yellow]")
        return

    diffs = engine.diff()

    if not diffs:
        console.print("[green]Fark tespit edilmedi, her şey senkron![/green]")
        return

    for eid, diff_data in diffs.items():
        table = Table(
            title=f"📋 {diff_data['name']} - Vault Farkları ({diff_data['total_diff']} fark)",
            box=box.ROUNDED,
            border_style="yellow" if diff_data["total_diff"] > 0 else "green"
        )
        table.add_column("Kategori", style="bold")
        table.add_column("Anahtar", style="dim")
        table.add_column("Sayı", justify="right")

        if diff_data["only_in_vault"]:
            keys = "\n".join(diff_data["only_in_vault"][:10])
            extra = f"\n... ve {len(diff_data['only_in_vault']) - 10} daha" if len(diff_data["only_in_vault"]) > 10 else ""
            table.add_row("Sadece Vault'ta", keys + extra, str(len(diff_data["only_in_vault"])))

        if diff_data["only_in_editor"]:
            keys = "\n".join(diff_data["only_in_editor"][:10])
            extra = f"\n... ve {len(diff_data['only_in_editor']) - 10} daha" if len(diff_data["only_in_editor"]) > 10 else ""
            table.add_row("Sadece Editörde", keys + extra, str(len(diff_data["only_in_editor"])))

        if diff_data["different_values"]:
            keys = "\n".join(diff_data["different_values"][:10])
            extra = f"\n... ve {len(diff_data['different_values']) - 10} daha" if len(diff_data["different_values"]) > 10 else ""
            table.add_row("Farklı Değerler", keys + extra, str(len(diff_data["different_values"])))

        if diff_data["total_diff"] == 0:
            table.add_row("✅ Senkron", "Tüm ayarlar eşleşiyor", "0")

        console.print(table)


# ─── Extensions Komutu ───────────────────────────────────────────────────────

def cmd_extensions(engine: SyncEngine):
    """Eklenti senkronizasyonu."""
    table = Table(
        title="🧩 Eklenti Durumu",
        box=box.ROUNDED,
        border_style="magenta"
    )
    table.add_column("Editör", style="bold")
    table.add_column("CLI", justify="center")
    table.add_column("Eklenti Sayısı", justify="right")

    editor_exts = {}
    for eid, einfo in engine.editors.items():
        exts = ExtensionManager.list_extensions(eid)
        editor_exts[eid] = exts
        table.add_row(
            einfo["name"],
            "✅" if einfo["has_cli"] else "❌",
            str(len(exts))
        )

    console.print(table)

    if len(editor_exts) > 1 and Confirm.ask("\nEklentileri senkronize etmek ister misiniz?", default=False):
        with console.status("[bold green]Eklentiler senkronize ediliyor..."):
            engine.sync_extensions_all()
        console.print("\n[bold green]✅ Eklenti senkronizasyonu tamamlandı![/bold green]")


# ─── Backups Komutu ──────────────────────────────────────────────────────────

def cmd_backups(engine: SyncEngine):
    """Yedekleri listele."""
    backups = engine.backup_mgr.list_backups()

    if not backups:
        console.print("[yellow]Henüz yedek yok.[/yellow]")
        return

    table = Table(
        title="💾 Yedekler",
        box=box.ROUNDED,
        border_style="blue"
    )
    table.add_column("#", style="bold cyan", justify="right")
    table.add_column("Ad", style="bold")
    table.add_column("Tarih", style="dim")
    table.add_column("Boyut", justify="right")

    for i, backup in enumerate(backups, 1):
        size_kb = backup["size"] / 1024
        table.add_row(
            str(i),
            backup["name"],
            backup["date"][:19],
            f"{size_kb:.1f} KB"
        )

    console.print(table)


# ─── Restore Komutu ──────────────────────────────────────────────────────────

def cmd_restore(engine: SyncEngine, backup_name: str = None):
    """Yedekten geri yükle."""
    backups = engine.backup_mgr.list_backups()
    if not backups:
        console.print("[yellow]Henüz yedek yok.[/yellow]")
        return

    if not backup_name:
        cmd_backups(engine)
        choice = Prompt.ask(
            "\nGeri yüklenecek yedek numarası",
            choices=[str(i) for i in range(1, len(backups) + 1)]
        )
        backup_name = backups[int(choice) - 1]["name"]

    # Hangi editöre geri yüklenecek
    console.print("\n[bold]Hedef editör seçin:[/bold]")
    editors_list = list(engine.editors.items())
    for i, (eid, einfo) in enumerate(editors_list, 1):
        console.print(f"  [cyan]{i}[/cyan]. {einfo['name']}")

    choice = Prompt.ask(
        "Seçiminiz",
        choices=[str(i) for i in range(1, len(editors_list) + 1)]
    )
    target_id, target_info = editors_list[int(choice) - 1]

    if Confirm.ask(f"\n{backup_name} -> {target_info['name']} geri yüklensin mi?"):
        success = engine.backup_mgr.restore(backup_name, target_info["path"])
        if success:
            console.print(f"\n[bold green]✅ Geri yükleme tamamlandı![/bold green]")
        else:
            console.print(f"\n[bold red]❌ Geri yükleme başarısız![/bold red]")


# ─── Workspaces Komutu ───────────────────────────────────────────────────────

def cmd_workspaces(engine: SyncEngine):
    """Workspace'leri listele."""
    workspaces = engine.workspace_syncer.discover_workspaces()

    if not workspaces:
        console.print("[yellow]Hiçbir workspace bulunamadı.[/yellow]")
        return

    table = Table(
        title="📁 Emare Workspace'leri",
        box=box.ROUNDED,
        border_style="cyan"
    )
    table.add_column("#", style="bold cyan", justify="right")
    table.add_column("Proje", style="bold white")
    table.add_column(".vscode Dosyaları", style="dim")

    for i, ws in enumerate(workspaces, 1):
        table.add_row(
            str(i),
            ws["name"],
            ", ".join(ws["files"]) if ws["files"] else "boş"
        )

    console.print(table)

    if Confirm.ask("\nWorkspace ayarlarını vault'a toplamak ister misiniz?", default=False):
        with console.status("[bold green]Workspace ayarları toplanıyor..."):
            collected = engine.workspace_syncer.collect_workspace_settings()
        console.print(f"\n[bold green]✅ {len(collected)} workspace ayarı toplandı![/bold green]")


# ─── Watch Komutu ────────────────────────────────────────────────────────────

def cmd_watch(engine: SyncEngine):
    """Dosya değişikliklerini izle ve otomatik senkronize et."""
    interval = engine.config.get("auto_sync_interval_minutes", 30) * 60

    console.print(f"\n[bold cyan]👁️  İzleme modu başlatıldı[/bold cyan]")
    console.print(f"    Kontrol aralığı: {interval // 60} dakika")
    console.print("    Durdurmak için Ctrl+C\n")

    running = True

    def stop_handler(sig, frame):
        nonlocal running
        running = False
        console.print("\n[yellow]İzleme durduruluyor...[/yellow]")

    signal.signal(signal.SIGINT, stop_handler)

    last_hashes = {}
    # İlk hash'leri al
    for eid, einfo in engine.editors.items():
        settings = einfo["path"] / "settings.json"
        last_hashes[eid] = file_hash(settings) if settings.exists() else ""

    cycle = 0
    while running:
        cycle += 1
        changed = False

        for eid, einfo in engine.editors.items():
            settings = einfo["path"] / "settings.json"
            current_hash = file_hash(settings) if settings.exists() else ""

            if current_hash != last_hashes.get(eid, ""):
                console.print(f"[yellow]🔔 Değişiklik tespit edildi: {einfo['name']}[/yellow]")
                changed = True
                last_hashes[eid] = current_hash

        if changed:
            console.print("[green]🔄 Otomatik senkronizasyon başlıyor...[/green]")
            engine.sync()
            console.print("[green]✅ Senkronizasyon tamamlandı[/green]")
            # Hash'leri güncelle
            for eid, einfo in engine.editors.items():
                settings = einfo["path"] / "settings.json"
                last_hashes[eid] = file_hash(settings) if settings.exists() else ""
        else:
            now = datetime.now().strftime("%H:%M:%S")
            console.print(f"  [{now}] Döngü #{cycle} - Değişiklik yok", style="dim")

        # Bekle
        for _ in range(interval):
            if not running:
                break
            time.sleep(1)

    console.print("[bold cyan]İzleme durduruldu.[/bold cyan]")


# ─── İnteraktif Menü ─────────────────────────────────────────────────────────

def interactive_menu(engine: SyncEngine):
    """Ana interaktif menü."""
    while True:
        console.print("\n[bold cyan]─── Ana Menü ───[/bold cyan]")
        console.print("  [cyan]1[/cyan]. 📊 Durum Raporu")
        console.print("  [cyan]2[/cyan]. ⬇️  Pull (Editörden Vault'a)")
        console.print("  [cyan]3[/cyan]. ⬆️  Push (Vault'tan Editörlere)")
        console.print("  [cyan]4[/cyan]. 🔄 Tam Senkronizasyon")
        console.print("  [cyan]5[/cyan]. 📋 Farkları Göster")
        console.print("  [cyan]6[/cyan]. 🧩 Eklenti Senkronizasyonu")
        console.print("  [cyan]7[/cyan]. 💾 Yedekler")
        console.print("  [cyan]8[/cyan]. 📁 Workspace'ler")
        console.print("  [cyan]9[/cyan]. 👁️  İzleme Modu")
        console.print("  [cyan]0[/cyan]. 🚪 Çıkış")

        choice = Prompt.ask("\nSeçiminiz", choices=["0","1","2","3","4","5","6","7","8","9"], default="1")

        if choice == "0":
            console.print("[bold cyan]Hoşça kalın! 👋[/bold cyan]")
            break
        elif choice == "1":
            cmd_status(engine)
        elif choice == "2":
            cmd_pull(engine)
        elif choice == "3":
            cmd_push(engine)
        elif choice == "4":
            cmd_sync(engine)
        elif choice == "5":
            cmd_diff(engine)
        elif choice == "6":
            cmd_extensions(engine)
        elif choice == "7":
            cmd_backups(engine)
        elif choice == "8":
            cmd_workspaces(engine)
        elif choice == "9":
            cmd_watch(engine)


# ─── Ana Giriş Noktası ──────────────────────────────────────────────────────

def main():
    show_banner()

    engine = SyncEngine()

    if len(sys.argv) < 2:
        interactive_menu(engine)
        return

    command = sys.argv[1].lower()
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    commands = {
        "status": lambda: cmd_status(engine),
        "pull": lambda: cmd_pull(engine, arg),
        "push": lambda: cmd_push(engine, arg),
        "sync": lambda: cmd_sync(engine),
        "diff": lambda: cmd_diff(engine),
        "extensions": lambda: cmd_extensions(engine),
        "backups": lambda: cmd_backups(engine),
        "restore": lambda: cmd_restore(engine, arg),
        "workspaces": lambda: cmd_workspaces(engine),
        "watch": lambda: cmd_watch(engine),
    }

    if command in commands:
        commands[command]()
    elif command in ("help", "--help", "-h"):
        console.print(__doc__)
    else:
        console.print(f"[red]Bilinmeyen komut: {command}[/red]")
        console.print(f"Kullanılabilir komutlar: {', '.join(commands.keys())}")


if __name__ == "__main__":
    main()
