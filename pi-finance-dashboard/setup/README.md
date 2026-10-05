# Setup: run order

Run everything on the Pi from the repo folder. Manual steps are in **bold**.

| Step | Script | Manual part |
|---|---|---|
| 1 | `01_install.sh` | — |
| 2 | `02_configure.sh` | **Plaid `client_id` + Production secret; choose a dashboard password** |
| 3 | `preflight.sh` | — (validates keys; creates no bank connection) |
| 4 | `03_webserver.sh` | — |
| 5 | `04_link_cards.sh` | **From a laptop: `ssh -L 4700:localhost:4700 <user>@<pi-ip>`, open `http://localhost:4700`, link each bank, click "I'm done"** |
| 6 | `05_sync_now.sh` | — |
| 7 | `06_schedule.sh` | — |
| 8 | `09_duckdns.sh` *(optional)* | **Create a free subdomain + copy your token at duckdns.org** |
| 9 | `07_wireguard.sh` *(optional)* | **Router: forward UDP 51820 to the Pi. Scan the QR code with the WireGuard app** |
| 10 | `10_insights.sh` *(optional)* | **Anthropic API key (workspace-scoped) + Gmail App Password** |
| ✓ | `98_check.sh` | — |

The dashboard is available at:
- At home: `http://<pi-ip>:8000`
- Over the VPN: `http://10.6.0.1:8000`

## Tips

- **Reserve the Pi's IP in your router's DHCP settings** so the port forward keeps working.
- **Use a single network interface.** If the Pi is on both Ethernet and Wi-Fi, add `dtoverlay=disable-wifi` to `/boot/firmware/config.txt`.
- **Test remote access over cellular, not home Wi-Fi.** Many routers can't loop back to their own public IP.
- **Link each bank only once.** Plaid Trial connections can't be freed up after removal.
- **To re-link a bank later**, re-run `04_link_cards.sh`.
- **To add a VPN device**, re-run `07_wireguard.sh` with a new device name.
