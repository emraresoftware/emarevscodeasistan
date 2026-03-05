# 🔄 Emare VS Code Asistan

Tüm VS Code kurulumlarının (VS Code, Cursor, VSCodium, Windsurf vb.) ayarlarını **merkezi olarak senkronize eden** araç.

## 🎯 Ne Yapar?

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
