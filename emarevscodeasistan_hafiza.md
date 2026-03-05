# Emare VS Code Asistan - Proje Hafızası

## Proje Özeti
- **Ad**: Emare VS Code Asistan
- **Tür**: Developer Tool / Settings Sync
- **Teknoloji**: Python, Rich, Watchdog
- **Port**: N/A (CLI aracı)
- **Durum**: development

## Temel Özellikler
1. Tüm VS Code varyantlarının ayarlarını senkronize eder (VS Code, Cursor, VSCodium, Windsurf)
2. Merkezi vault deposu ile tek doğru kaynak prensibi
3. Otomatik yedekleme ve geri yükleme
4. Dosya izleme ile otomatik senkronizasyon
5. Eklenti yönetimi ve çapraz editör senkronizasyon
6. Emare workspace ayarlarını merkezi yönetim
7. Rich tabanlı interaktif CLI

## Yapı
- `sync_engine.py`: Ana senkronizasyon motoru (SyncEngine, Vault, BackupManager, ExtensionManager, WorkspaceSyncer)
- `cli.py`: Rich CLI arayüzü
- `watcher.py`: Watchdog tabanlı dosya izleyici
- `config.json`: Yapılandırma

## Notlar
- İlk çalıştırmada `pull` komutu ile en kapsamlı editörden ayarlar vault'a çekilmeli
- `ignore_keys` ile kişisel tercihler (tema, zoom vb.) senkronizasyon dışında tutulabilir
- Emare Hub ekosisteminin parçası
