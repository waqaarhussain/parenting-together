"""Render representative configs for Caddy's own parser in CI; never issue certs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.configure_site import render_config, site_config

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
template=Path('deploy/Caddyfile.template').read_text()
for name,host in [('hostname','app.example.com'),('ipv4','93.184.216.34'),('ipv6','2606:4700:4700::1111')]:
    (root/(name+'.caddy')).write_text(render_config(site_config(host),template))
(root/'Caddyfile').write_text(Path('deploy/Caddyfile').read_text())
(root/'parenting-together-site.caddy').write_text((root/'hostname.caddy').read_text())
