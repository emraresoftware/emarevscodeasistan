# 🔄 Emare VS Code Asistan

Tüm makinelerdeki VS Code ayarlarını **merkezi Linux sunucu** üzerinden senkronize eden araç.

## 🎯 Mimari

```
┌──────────────────┐         ┌───────────────────┐         ┌──────────────────┐
│   Mac (client)   │         │  Linux Sunucu     │         │  PC (client)     │
│  VS Code         │◄───────►│  FastAPI Server   │◄───────►│  VS Code         │
│  python client.py│  HTTP   │  python server.py │  HTTP   │  python client.py│
└──────────────────┘         │                   │         └──────────────────┘
                             │  vault/           │
                             │  ├─ settings.json │
                             │  ├─ keybindings   │
                             │  ├─ mcp.json      │
                             │  ├─ snippets/     │
                             │  └─ extensions/   │
                             └───────────────────┘
```

**Sunucu** (Linux): Merkezi vault deposu + REST API
**İstemci** (Mac/Linux/Win): Her makinede çalışır, sunucuya push/pull yapar

## 📋 Senkronize Edilen Öğeler

| Öğe | Açıklama |
|-----|----------|
| `settings.json` | Tüm VS Code ayarları |
| `keybindings.json` | Klavye kısayolları |
| `mcp.json` | MCP sunucu yapılandırmaları |
| `snippets/` | Kod parçacıkları |
| `extensions` | Eklenti listesi (otomatik yükleme) |
| `profiles/` | VS Code profilleri |

## 🚀 Sunucu Kurulumu (Linux)

### Otomatik Kurulum
```bash
cd deploy/
bash deploy.sh
```

### Manuel
```bash
mkdir -p /opt/emarevscodeasistan
cp server.py requirements.txt /opt/emarevscodeasistan/
cd /opt/emarevscodeasistan
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py --port 8585
```

İlk çalıştırmada **Master API Key** otomatik oluşturulur.

### Systemd Servisi
```bash
sudo cp deploy/emarevscodeasistan.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now emarevscodeasistan
```

## 💻 İstemci Kurulumu (Her Makine)

```bash
pip install requests rich
python client.py setup
```

## 🔧 Kullanım

```bash
python client.py               # İnteraktif menü
python client.py status         # Durum + hash karşılaştırma
python client.py push           # Ayarları sunucuya gönder
python client.py pull           # Sunucudan çek
python client.py sync           # Push + Pull
python client.py watch          # Otomatik izleme
```

## 🔒 Güvenlik

- API Key tabanlı kimlik doğrulama (read/write/admin)
- Master key ilk çalıştırmada oluşur
- Systemd ile izole çalışma
- Her sync öncesi otomatik yedekleme

## 📁 Yapı

```
emarevscodeasistan/
├── server.py           # FastAPI sunucu (Linux)
├── client.py           # İstemci (her makine)
├── sync_engine.py      # Yerel motor (opsiyonel)
├── cli.py              # Yerel CLI (opsiyonel)
├── requirements.txt
├── deploy/
│   ├── deploy.sh       # Otomatik sunucu kurulum
│   └── *.service       # Systemd servisi
├── vault/              # Merkezi depo (sunucu)
├── backups/            # Yedekler (sunucu)
└── auth.json           # API anahtarları (sunucuda oluşur)
```

---

**Emare VS Code Asistan** — *Bir yerde ayarla, her yerde kullan.* 🔄

- **settings.json** → Tüm editör ayarlarını senkronize eder
- **keybindings.json** → Klavye kısayollarını senkronize eder
- **snippets/** → Kod parçacıklarını senkronize eder
- **mcp.json** → MCP sunucu yapılandırmalarını senkronize eder
- **Eklentiler** → Yüklü eklentileri editörler arası senkronize eder
- **Profiller** → VS Code profillerini yedekler ve yönetir
- **Workspace ayarları** → Emare projelerinin .vscode ayarlarını toplar

## 📋 Mimari

```
emarevscodeasistan/
├── config.json          # Yapılandırma dosyası
├── sync_engine.py       # Ana senkronizasyon motoru
├── cli.py               # Rich tabanlı CLI arayüzü
├── watcher.py           # Dosya değişiklik izleyicisi (watchdog)
├── requirements.txt     # Python bağımlılıkları
├── vault/               # Merkezi ayar deposu (tek doğru kaynak)
│   ├── settings.json
│   ├── keybindings.json
│   ├── mcp.json
│   ├── snippets/
│   ├── profiles/
│   ├── extensions/
│   └── workspaces/
├── backups/             # Otomatik yedekler
├── state.json           # Son senkronizasyon durumu
└── sync.log             # Senkronizasyon logları
```

## 🚀 Kurulum

```bash
cd emarevscodeasistan
pip install -r requirements.txt
```

## 💻 Kullanım

### İnteraktif Menü
```bash
python cli.py
```

### Komut Satırı
```bash
python cli.py status          # Durum raporu
python cli.py pull [editor]   # Editörden ayarları çek (Vault'a)
python cli.py push [editor]   # Vault'tan editörlere dağıt
python cli.py sync            # Tam senkronizasyon (pull + push)
python cli.py diff            # Editörler arası farkları göster
python cli.py extensions      # Eklenti senkronizasyonu
python cli.py backups         # Yedekleri listele
python cli.py restore <name>  # Yedeği geri yükle
python cli.py workspaces      # Emare workspace'lerini listele
python cli.py watch           # Otomatik izleme modu
```

### Dosya İzleyici (Daemon)
```bash
python watcher.py   # Ayar değişikliklerini otomatik algılayıp senkronize eder
```

## 🔄 Senkronizasyon Akışı

```
┌─────────────┐     PULL      ┌──────────┐     PUSH      ┌─────────────┐
│  VS Code    │ ────────────→ │  VAULT   │ ────────────→ │  Cursor     │
│  (kaynak)   │               │ (merkez) │               │  (hedef)    │
└─────────────┘               └──────────┘               └─────────────┘
                                   │
                                   │ PUSH
                                   ▼
                              ┌──────────┐
                              │ VSCodium │
                              │ (hedef)  │
                              └──────────┘
```

1. **Pull**: Bir editörden (genellikle en kapsamlı olan) ayarları vault'a çeker
2. **Push**: Vault'taki ayarları tüm hedef editörlere dağıtır
3. **Sync**: Pull + Push işlemini tek komutta yapar

## ⚙️ Yapılandırma (config.json)

| Alan | Açıklama |
|------|----------|
| `editors` | Desteklenen editörler ve yolları |
| `sync_items` | Senkronize edilecek öğeler |
| `ignore_keys` | Senkronizasyonda atlanacak ayarlar (örn: zoom, tema) |
| `workspace_sync` | Emare workspace ayar senkronizasyonu |
| `max_backups` | Tutulacak maksimum yedek sayısı |
| `conflict_resolution` | Çakışma durumunda davranış |

### Editör ekleme/çıkarma

`config.json` dosyasında `editors` altında `"enabled": true/false` ile editörleri aktif/pasif yapabilirsiniz.

### Senkronize edilmeyen ayarlar

`ignore_keys` listesindeki ayarlar her editörde farklı kalabilir:
- `window.zoomLevel` → Her ekranda farklı olabilir
- `workbench.colorTheme` → Kişisel tercih
- `editor.fontSize` → Monitöre göre değişir

## 💾 Yedekleme

Her senkronizasyon öncesi otomatik yedek alınır. Yedekler `backups/` klasöründe tutulur.

```bash
python cli.py backups          # Yedekleri listele
python cli.py restore <isim>   # Yedeği geri yükle
```

## 🏗️ Emare Hub Entegrasyonu

Bu araç Emare Hub ekosisteminin bir parçasıdır. `projects.json` üzerinden kaydedilir ve hub üzerinden yönetilebilir.

---

**Emare VS Code Asistan** — *Bir yerde ayarla, her yerde kullan.* 🔄
