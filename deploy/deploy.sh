#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Emare VS Code Asistan - Linux Sunucu Kurulum Scripti
# Bu scripti sunucuda çalıştırın:
#   bash deploy.sh
# ─────────────────────────────────────────────────────────────

set -e

APP_DIR="/opt/emarevscodeasistan"
SERVICE_NAME="emarevscodeasistan"
PORT=8585
USER=$(whoami)

echo "╔═══════════════════════════════════════════════╗"
echo "║   🔄  Emare VS Code Asistan - Sunucu Kurulum  ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""

# 1. Gerekli paketler
echo "📦 Gerekli paketler yükleniyor..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-venv python3-pip
elif command -v dnf &> /dev/null; then
    sudo dnf install -y python3 python3-pip
elif command -v yum &> /dev/null; then
    sudo yum install -y python3 python3-pip
fi

# 2. Uygulama dizini
echo "📁 Uygulama dizini oluşturuluyor: $APP_DIR"
sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"

# 3. Dosyaları kopyala
echo "📄 Dosyalar kopyalanıyor..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

cp "$PARENT_DIR/server.py" "$APP_DIR/"
cp "$PARENT_DIR/requirements.txt" "$APP_DIR/"
mkdir -p "$APP_DIR/vault" "$APP_DIR/backups"

# 4. Virtual environment
echo "🐍 Python sanal ortam oluşturuluyor..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip -q
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# 5. Systemd servisi
echo "⚙️  Systemd servisi kuruluyor..."
sudo cp "$SCRIPT_DIR/emarevscodeasistan.service" /etc/systemd/system/
sudo sed -i "s|User=emre|User=$USER|g" /etc/systemd/system/emarevscodeasistan.service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

# 6. Firewall
echo "🔥 Firewall kuralı ekleniyor (port $PORT)..."
if command -v ufw &> /dev/null; then
    sudo ufw allow "$PORT/tcp" 2>/dev/null || true
elif command -v firewall-cmd &> /dev/null; then
    sudo firewall-cmd --permanent --add-port="$PORT/tcp" 2>/dev/null || true
    sudo firewall-cmd --reload 2>/dev/null || true
fi

# 7. API Key göster
echo ""
echo "═══════════════════════════════════════════════"
sleep 2
if [ -f "$APP_DIR/auth.json" ]; then
    MASTER_KEY=$(python3 -c "import json; d=json.load(open('$APP_DIR/auth.json')); print([k for k,v in d['keys'].items() if v['name']=='master'][0])")
    echo "🔑 Master API Key: $MASTER_KEY"
    echo ""
    echo "📋 Bu anahtarı istemcilerde kullanın:"
    echo "   python client.py setup"
    echo "   Sunucu: http://$(hostname -I | awk '{print $1}'):$PORT"
    echo "   API Key: $MASTER_KEY"
else
    echo "⚠️  auth.json oluşturulmadı. Servisi kontrol edin:"
    echo "   sudo systemctl status $SERVICE_NAME"
fi

echo ""
echo "═══════════════════════════════════════════════"
echo "✅ Kurulum tamamlandı!"
echo ""
echo "Servis durumu:  sudo systemctl status $SERVICE_NAME"
echo "Loglar:         sudo journalctl -u $SERVICE_NAME -f"
echo "Yeniden başlat: sudo systemctl restart $SERVICE_NAME"
echo "═══════════════════════════════════════════════"
