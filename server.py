#!/usr/bin/env python3
"""
Emare VS Code Asistan - Sunucu (Server)
Linux sunucu üzerinde çalışır. Merkezi vault'u tutar.
İstemciler (Mac/Win/Linux) buraya bağlanıp ayarları push/pull yapar.

Çalıştırma:
    python server.py                    # Varsayılan port 8585
    python server.py --port 9090        # Özel port
    python server.py --host 0.0.0.0     # Tüm arayüzlerden dinle
"""

import json
import os
import shutil
import hashlib
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ─── Sabitler ─────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.resolve()
VAULT_DIR = BASE_DIR / "vault"
BACKUP_DIR = BASE_DIR / "backups"
LOG_FILE = BASE_DIR / "server.log"
STATE_FILE = BASE_DIR / "state.json"
AUTH_FILE = BASE_DIR / "auth.json"
MAX_BACKUPS = 20

# Vault alt dizinleri
for d in ["snippets", "profiles", "extensions", "workspaces"]:
    (VAULT_DIR / d).mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


# ─── Yardımcılar ─────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] [{level}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def file_hash(filepath: Path) -> str:
    if not filepath.exists():
        return ""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"clients": {}, "last_activity": None, "sync_count": 0}


def save_state(state: dict):
    state["last_activity"] = datetime.now().isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_auth() -> dict:
    """API anahtarlarını yükle. Yoksa ilk anahtarı oluştur."""
    if AUTH_FILE.exists():
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # İlk çalıştırmada master key oluştur
    master_key = secrets.token_urlsafe(32)
    auth = {
        "keys": {
            master_key: {
                "name": "master",
                "created": datetime.now().isoformat(),
                "permissions": ["read", "write", "admin"]
            }
        }
    }
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(auth, f, indent=2)
    log(f"🔑 Master API Key oluşturuldu: {master_key}", "AUTH")
    log(f"   Bu anahtarı istemcilerde kullanın!", "AUTH")
    return auth


def pretty_json(data) -> str:
    return json.dumps(data, indent=4, ensure_ascii=False, sort_keys=False)


def create_backup(item_name: str):
    """Vault öğesini yedekle."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    src = VAULT_DIR / item_name
    if not src.exists():
        return
    backup_path = BACKUP_DIR / f"{item_name.replace('/', '_')}_{ts}"
    if src.is_file():
        backup_path = BACKUP_DIR / f"{src.stem}_{ts}{src.suffix}"
        shutil.copy2(src, backup_path)
    elif src.is_dir():
        shutil.copytree(src, backup_path, dirs_exist_ok=True)
    # Eski yedekleri temizle
    prefix = item_name.replace("/", "_").split(".")[0]
    backups = sorted(
        [f for f in BACKUP_DIR.iterdir() if f.name.startswith(prefix)],
        key=lambda x: x.stat().st_mtime, reverse=True
    )
    for old in backups[MAX_BACKUPS:]:
        if old.is_file():
            old.unlink()
        elif old.is_dir():
            shutil.rmtree(old)


# ─── Auth Middleware ──────────────────────────────────────────────────────────

auth_data = load_auth()


def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """API key doğrulama."""
    if x_api_key not in auth_data["keys"]:
        raise HTTPException(status_code=401, detail="Geçersiz API Key")
    return auth_data["keys"][x_api_key]


def require_write(auth: dict = Depends(verify_api_key)):
    if "write" not in auth.get("permissions", []):
        raise HTTPException(status_code=403, detail="Yazma yetkisi yok")
    return auth


def require_admin(auth: dict = Depends(verify_api_key)):
    if "admin" not in auth.get("permissions", []):
        raise HTTPException(status_code=403, detail="Admin yetkisi yok")
    return auth


# ─── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(

# === Emare Feedback ===
from feedback_router import router as feedback_router
app.include_router(feedback_router, prefix="/api/feedback", tags=["feedback"])
# ======================

    title="Emare VS Code Asistan",
    description="VS Code ayar senkronizasyon sunucusu",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Modeller ────────────────────────────────────────────────────────────────

class PushRequest(BaseModel):
    client_id: str
    client_name: str = ""
    os_type: str = ""
    editor: str = "vscode"


class KeyCreateRequest(BaseModel):
    name: str
    permissions: list = ["read", "write"]


# ─── Durum Endpoint'leri ─────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "Emare VS Code Asistan",
        "version": "2.0.0",
        "status": "running",
        "vault_items": {
            "settings": (VAULT_DIR / "settings.json").exists(),
            "keybindings": (VAULT_DIR / "keybindings.json").exists(),
            "mcp": (VAULT_DIR / "mcp.json").exists(),
            "snippets": any((VAULT_DIR / "snippets").iterdir()) if (VAULT_DIR / "snippets").exists() else False,
            "extensions": any((VAULT_DIR / "extensions").iterdir()) if (VAULT_DIR / "extensions").exists() else False,
        }
    }


@app.get("/status")
async def status(auth: dict = Depends(verify_api_key)):
    state = load_state()
    vault_files = {}
    for f in VAULT_DIR.rglob("*"):
        if f.is_file():
            rel = str(f.relative_to(VAULT_DIR))
            vault_files[rel] = {
                "size": f.stat().st_size,
                "hash": file_hash(f),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
            }
    return {
        "state": state,
        "vault_files": vault_files,
        "backup_count": len(list(BACKUP_DIR.iterdir())),
    }


# ─── Settings Endpoint'leri ──────────────────────────────────────────────────

@app.get("/settings")
async def get_settings(auth: dict = Depends(verify_api_key)):
    """Vault'taki settings.json'u döndür."""
    fp = VAULT_DIR / "settings.json"
    if not fp.exists():
        raise HTTPException(404, "settings.json henüz yüklenmemiş")
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


@app.put("/settings")
async def put_settings(
    data: dict,
    client_id: str = Header("unknown", alias="X-Client-ID"),
    auth: dict = Depends(require_write)
):
    """settings.json'u vault'a kaydet."""
    fp = VAULT_DIR / "settings.json"
    create_backup("settings.json")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(pretty_json(data))
    state = load_state()
    state["sync_count"] = state.get("sync_count", 0) + 1
    state.setdefault("clients", {})[client_id] = {
        "last_push": datetime.now().isoformat(),
        "item": "settings"
    }
    save_state(state)
    log(f"Settings güncellendi by {client_id}")
    return {"status": "ok", "hash": file_hash(fp)}


@app.get("/settings/hash")
async def get_settings_hash(auth: dict = Depends(verify_api_key)):
    fp = VAULT_DIR / "settings.json"
    return {"hash": file_hash(fp), "exists": fp.exists()}


# ─── Keybindings Endpoint'leri ───────────────────────────────────────────────

@app.get("/keybindings")
async def get_keybindings(auth: dict = Depends(verify_api_key)):
    fp = VAULT_DIR / "keybindings.json"
    if not fp.exists():
        raise HTTPException(404, "keybindings.json henüz yüklenmemiş")
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


@app.put("/keybindings")
async def put_keybindings(
    request: Request,
    client_id: str = Header("unknown", alias="X-Client-ID"),
    auth: dict = Depends(require_write)
):
    data = await request.json()
    fp = VAULT_DIR / "keybindings.json"
    create_backup("keybindings.json")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=4, ensure_ascii=False))
    log(f"Keybindings güncellendi by {client_id}")
    return {"status": "ok", "hash": file_hash(fp)}


@app.get("/keybindings/hash")
async def get_keybindings_hash(auth: dict = Depends(verify_api_key)):
    fp = VAULT_DIR / "keybindings.json"
    return {"hash": file_hash(fp), "exists": fp.exists()}


# ─── MCP Endpoint'leri ───────────────────────────────────────────────────────

@app.get("/mcp")
async def get_mcp(auth: dict = Depends(verify_api_key)):
    fp = VAULT_DIR / "mcp.json"
    if not fp.exists():
        raise HTTPException(404, "mcp.json henüz yüklenmemiş")
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


@app.put("/mcp")
async def put_mcp(
    data: dict,
    client_id: str = Header("unknown", alias="X-Client-ID"),
    auth: dict = Depends(require_write)
):
    fp = VAULT_DIR / "mcp.json"
    create_backup("mcp.json")
    with open(fp, "w", encoding="utf-8") as f:
        f.write(pretty_json(data))
    log(f"MCP güncellendi by {client_id}")
    return {"status": "ok", "hash": file_hash(fp)}


# ─── Snippets Endpoint'leri ──────────────────────────────────────────────────

@app.get("/snippets")
async def list_snippets(auth: dict = Depends(verify_api_key)):
    snippets_dir = VAULT_DIR / "snippets"
    files = {}
    for f in snippets_dir.iterdir():
        if f.is_file() and f.suffix == ".json":
            with open(f, "r", encoding="utf-8") as fh:
                files[f.name] = json.load(fh)
    return files


@app.get("/snippets/{filename}")
async def get_snippet(filename: str, auth: dict = Depends(verify_api_key)):
    fp = VAULT_DIR / "snippets" / filename
    if not fp.exists():
        raise HTTPException(404, f"Snippet bulunamadı: {filename}")
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


@app.put("/snippets/{filename}")
async def put_snippet(
    filename: str,
    data: dict,
    auth: dict = Depends(require_write)
):
    fp = VAULT_DIR / "snippets" / filename
    with open(fp, "w", encoding="utf-8") as f:
        f.write(pretty_json(data))
    log(f"Snippet güncellendi: {filename}")
    return {"status": "ok"}


# ─── Extensions Endpoint'leri ────────────────────────────────────────────────

@app.get("/extensions")
async def get_extensions(auth: dict = Depends(verify_api_key)):
    """Birleştirilmiş eklenti listesini döndür."""
    all_ext = set()
    ext_dir = VAULT_DIR / "extensions"
    for fp in ext_dir.glob("*.json"):
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
            all_ext.update(data.get("extensions", []))
    return {"extensions": sorted(all_ext), "count": len(all_ext)}


@app.put("/extensions")
async def put_extensions(
    data: dict,
    client_id: str = Header("unknown", alias="X-Client-ID"),
    auth: dict = Depends(require_write)
):
    """İstemcinin eklenti listesini kaydet."""
    exts = data.get("extensions", [])
    editor = data.get("editor", "unknown")
    safe = f"{client_id}_{editor}".replace(" ", "_").lower()
    fp = VAULT_DIR / "extensions" / f"{safe}.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump({
            "client_id": client_id,
            "editor": editor,
            "extensions": exts,
            "count": len(exts),
            "updated": datetime.now().isoformat()
        }, f, indent=2)
    log(f"Eklenti listesi güncellendi: {client_id}/{editor} ({len(exts)} eklenti)")
    return {"status": "ok", "count": len(exts)}


# ─── Profiles Endpoint'leri ──────────────────────────────────────────────────

@app.get("/profiles")
async def list_profiles(auth: dict = Depends(verify_api_key)):
    profiles = {}
    profiles_dir = VAULT_DIR / "profiles"
    for d in profiles_dir.iterdir():
        if d.is_dir():
            profiles[d.name] = [f.name for f in d.iterdir() if f.is_file()]
    return profiles


@app.get("/profiles/{profile_name}/{filename}")
async def get_profile_file(profile_name: str, filename: str, auth: dict = Depends(verify_api_key)):
    fp = VAULT_DIR / "profiles" / profile_name / filename
    if not fp.exists():
        raise HTTPException(404, f"Profil dosyası bulunamadı: {profile_name}/{filename}")
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── Toplu Sync Endpoint'i ───────────────────────────────────────────────────

@app.get("/sync/pull")
async def sync_pull(auth: dict = Depends(verify_api_key)):
    """
    Toplu pull - istemci tüm ayarları tek istekte çeker.
    Bandwidth tasarrufu: hash kontrolü ile sadece değişenleri çeker.
    """
    result = {}

    # Settings
    settings_fp = VAULT_DIR / "settings.json"
    if settings_fp.exists():
        with open(settings_fp, "r", encoding="utf-8") as f:
            result["settings"] = {"data": json.load(f), "hash": file_hash(settings_fp)}

    # Keybindings
    kb_fp = VAULT_DIR / "keybindings.json"
    if kb_fp.exists():
        with open(kb_fp, "r", encoding="utf-8") as f:
            result["keybindings"] = {"data": json.load(f), "hash": file_hash(kb_fp)}

    # MCP
    mcp_fp = VAULT_DIR / "mcp.json"
    if mcp_fp.exists():
        with open(mcp_fp, "r", encoding="utf-8") as f:
            result["mcp"] = {"data": json.load(f), "hash": file_hash(mcp_fp)}

    # Snippets
    snippets_dir = VAULT_DIR / "snippets"
    snippets = {}
    for fp in snippets_dir.iterdir():
        if fp.is_file() and fp.suffix == ".json":
            with open(fp, "r", encoding="utf-8") as f:
                snippets[fp.name] = json.load(f)
    if snippets:
        result["snippets"] = snippets

    # Extensions (birleştirilmiş)
    all_ext = set()
    for fp in (VAULT_DIR / "extensions").glob("*.json"):
        with open(fp, "r", encoding="utf-8") as f:
            all_ext.update(json.load(f).get("extensions", []))
    if all_ext:
        result["extensions"] = sorted(all_ext)

    return result


@app.post("/sync/push")
async def sync_push(
    data: dict,
    client_id: str = Header("unknown", alias="X-Client-ID"),
    auth: dict = Depends(require_write)
):
    """
    Toplu push - istemci tüm ayarları tek istekte gönderir.
    """
    pushed = []

    if "settings" in data:
        create_backup("settings.json")
        with open(VAULT_DIR / "settings.json", "w", encoding="utf-8") as f:
            f.write(pretty_json(data["settings"]))
        pushed.append("settings")

    if "keybindings" in data:
        create_backup("keybindings.json")
        with open(VAULT_DIR / "keybindings.json", "w", encoding="utf-8") as f:
            f.write(json.dumps(data["keybindings"], indent=4, ensure_ascii=False))
        pushed.append("keybindings")

    if "mcp" in data:
        create_backup("mcp.json")
        with open(VAULT_DIR / "mcp.json", "w", encoding="utf-8") as f:
            f.write(pretty_json(data["mcp"]))
        pushed.append("mcp")

    if "snippets" in data:
        for fname, content in data["snippets"].items():
            with open(VAULT_DIR / "snippets" / fname, "w", encoding="utf-8") as f:
                f.write(pretty_json(content))
        pushed.append("snippets")

    if "extensions" in data:
        editor = data.get("editor", "vscode")
        safe = f"{client_id}_{editor}".replace(" ", "_").lower()
        with open(VAULT_DIR / "extensions" / f"{safe}.json", "w", encoding="utf-8") as f:
            json.dump({
                "client_id": client_id, "editor": editor,
                "extensions": data["extensions"],
                "updated": datetime.now().isoformat()
            }, f, indent=2)
        pushed.append("extensions")

    state = load_state()
    state["sync_count"] = state.get("sync_count", 0) + 1
    state.setdefault("clients", {})[client_id] = {
        "last_push": datetime.now().isoformat(),
        "pushed_items": pushed
    }
    save_state(state)
    log(f"Toplu push: {client_id} -> {pushed}")
    return {"status": "ok", "pushed": pushed}


# ─── Hash Karşılaştırma ──────────────────────────────────────────────────────

@app.get("/sync/hashes")
async def get_all_hashes(auth: dict = Depends(verify_api_key)):
    """Tüm vault dosyalarının hash'leri - istemci bununla karşılaştırır."""
    hashes = {}
    for name in ["settings.json", "keybindings.json", "mcp.json"]:
        fp = VAULT_DIR / name
        if fp.exists():
            hashes[name] = file_hash(fp)
    return hashes


# ─── Admin: API Key Yönetimi ─────────────────────────────────────────────────

@app.post("/admin/keys")
async def create_key(req: KeyCreateRequest, auth: dict = Depends(require_admin)):
    """Yeni API key oluştur."""
    new_key = secrets.token_urlsafe(32)
    auth_data["keys"][new_key] = {
        "name": req.name,
        "created": datetime.now().isoformat(),
        "permissions": req.permissions
    }
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2)
    log(f"Yeni API Key oluşturuldu: {req.name}", "AUTH")
    return {"key": new_key, "name": req.name, "permissions": req.permissions}


@app.get("/admin/keys")
async def list_keys(auth: dict = Depends(require_admin)):
    return {
        k: {"name": v["name"], "permissions": v["permissions"], "created": v["created"]}
        for k, v in auth_data["keys"].items()
    }


@app.delete("/admin/keys/{key}")
async def delete_key(key: str, auth: dict = Depends(require_admin)):
    if key not in auth_data["keys"]:
        raise HTTPException(404, "Key bulunamadı")
    if auth_data["keys"][key].get("name") == "master":
        raise HTTPException(403, "Master key silinemez")
    del auth_data["keys"][key]
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2)
    return {"status": "deleted"}


# ─── Backup Endpoint'leri ────────────────────────────────────────────────────

@app.get("/backups")
async def list_backups(auth: dict = Depends(verify_api_key)):
    backups = []
    for item in sorted(BACKUP_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        size = item.stat().st_size if item.is_file() else sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
        backups.append({
            "name": item.name,
            "date": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
            "size": size
        })
    return backups


# ─── Başlatma ────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Emare VS Code Asistan Sunucu")
    parser.add_argument("--host", default="0.0.0.0", help="Dinleme adresi")
    parser.add_argument("--port", type=int, default=8585, help="Port numarası")
    parser.add_argument("--reload", action="store_true", help="Otomatik yeniden yükleme")
    args = parser.parse_args()

    log(f"🚀 Emare VS Code Asistan Sunucu başlatılıyor: {args.host}:{args.port}")
    print()

    # Master key'i göster
    for key, val in auth_data["keys"].items():
        if val.get("name") == "master":
            print(f"  🔑 Master API Key: {key}")
            print(f"  📋 İstemcilerde bu anahtarı kullanın")
            print()
            break

    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
