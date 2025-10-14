#!/bin/bash

PROJECT_DIR="/home/pi/rider-controller"
SERVICE_NAME="rider-controller"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "==================================="
echo "  Rider Controller Service Setup"
echo "==================================="

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "❌ Don't run this script as root/sudo"
    echo "   Run as: ./setup_service.sh"
    exit 1
fi

# Check if project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ Project directory not found: $PROJECT_DIR"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo "📦 Creating virtual environment..."
    cd "$PROJECT_DIR"
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment exists"
fi

# Create service file
echo ""
echo "📝 Creating systemd service file..."

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Rider Controller - Multi-Camera Orchestration Server
After=network-online.target chronyd.service
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=$PROJECT_DIR/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Increase file descriptor limit
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
EOF

echo "✓ Service file created: $SERVICE_FILE"

# Reload systemd
echo ""
echo "🔄 Reloading systemd..."
sudo systemctl daemon-reload

# Enable service
echo "✓ Enabling service to start on boot..."
sudo systemctl enable "$SERVICE_NAME"

echo ""
echo "==================================="
echo "  Setup Complete!"
echo "==================================="
echo ""
echo "Service Commands:"
echo "  Start:   sudo systemctl start $SERVICE_NAME"
echo "  Stop:    sudo systemctl stop $SERVICE_NAME"
echo "  Restart: sudo systemctl restart $SERVICE_NAME"
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "The service will now start automatically on boot."
echo ""
echo "Start the service now?"
read -p "Start service? (y/n): " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo systemctl start "$SERVICE_NAME"
    echo ""
    sleep 2
    sudo systemctl status "$SERVICE_NAME"
fi
