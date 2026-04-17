[Unit]
Description=Reverse SSH tunnel to VPS
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Environment="AUTOSSH_GATETIME=0"
ExecStart=/usr/bin/autossh -M 0 -N \
  -o "ServerAliveInterval 20" \
  -o "ServerAliveCountMax 3" \
  -o "ExitOnForwardFailure yes" \
  -o "StrictHostKeyChecking accept-new" \
  -i /root/.ssh/id_ed25519_vps_tunnel \
  -R __REVERSE_PORT__:localhost:22 \
  tunnel@89.124.69.165
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target