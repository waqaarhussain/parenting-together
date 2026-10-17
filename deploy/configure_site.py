"""Configure a hostname or public-IP HTTPS site, without changing app data."""
import argparse
import ipaddress
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

DEFAULT_EMAIL = 'waqaar06@hotmail.com'


def public_ip(value):
    address = ipaddress.ip_address(str(value).strip().strip('[]'))
    if not address.is_global or address.is_multicast:
        raise ValueError('Use a public IP assigned to this VPS, not a private or local address.')
    return str(address)


def normalize_host(value):
    value = value.strip()
    if '://' in value:
        parsed = urlsplit(value)
        if parsed.scheme not in ('https', 'http') or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port:
            raise ValueError('Enter just the hostname or public IP, without a port or path.')
        value = parsed.hostname or ''
    try:
        return public_ip(value), 'ip'
    except ValueError:
        pass
    value = value.rstrip('.').lower()
    if re.fullmatch(r'[0-9.]+', value):
        raise ValueError('That is not a public IP address.')
    labels = value.split('.')
    if len(value) > 253 or len(labels) < 2 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in labels):
        raise ValueError('Enter a valid public hostname, such as app.example.com.')
    if labels[-1] in ('localhost', 'local', 'internal', 'test', 'invalid') or value.endswith('.home.arpa'):
        raise ValueError('Use a public DNS hostname that points to this VPS.')
    return value, 'hostname'


def detect_public_ip():
    if os.environ.get('PT_PUBLIC_IP'):
        return public_ip(os.environ['PT_PUBLIC_IP'])
    try:
        interfaces = json.loads(subprocess.check_output(['ip', '-j', 'address', 'show', 'scope', 'global'], timeout=5))
        candidates = [item['local'] for interface in interfaces if isinstance(interface, dict)
                      for item in (interface.get('addr_info') or []) if isinstance(item, dict)
                      and isinstance(item.get('local'), str)]
        for value in sorted(candidates, key=lambda value: ':' in value):
            try:
                return public_ip(value)
            except ValueError:
                continue
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        with urlopen('https://api.ipify.org', timeout=8) as response:
            return public_ip(response.read(128).decode())
    except (OSError, ValueError):
        raise ValueError('Could not detect the public IP. Set PT_PUBLIC_IP to this VPS public IP and retry.') from None


def site_config(host, email=DEFAULT_EMAIL):
    host, mode = normalize_host(host)
    if not re.fullmatch(r'[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', email):
        raise ValueError('Invalid certificate contact email.')
    address = '[' + host + ']' if ':' in host else host
    return {'host': host, 'mode': mode, 'email': email, 'url': 'https://' + address}


def render_config(config, template):
    host, mode = normalize_host(config['host'])
    checked = site_config(host, config['email'])
    global_options = '{\n    default_sni ' + host + '\n}\n\n' if mode == 'ip' else ''
    if mode == 'ip':
        tls = '''    tls {
        issuer acme {
            dir https://acme-v02.api.letsencrypt.org/directory
            test_dir https://acme-v02.api.letsencrypt.org/directory
            email EMAIL
            profile shortlived
        }
    }'''
    else:
        tls = '''    tls {
        issuer acme {
            dir https://acme.zerossl.com/v2/DV90
            test_dir https://acme.zerossl.com/v2/DV90
            email EMAIL
        }
        issuer acme {
            dir https://acme-v02.api.letsencrypt.org/directory
            test_dir https://acme-v02.api.letsencrypt.org/directory
            email EMAIL
        }
    }'''
    return (global_options + template.replace('@@SITE_ADDRESS@@', checked['url'])
            .replace('@@TLS_CONFIG@@', tls.replace('EMAIL', checked['email'])))


def prompt_hostname():
    # stdin is the installer script itself when launched using curl | bash.
    try:
        with open('/dev/tty', 'w') as output, open('/dev/tty', 'r') as terminal:
            output.write('Hostname (leave blank to use this VPS public IP with HTTPS): ')
            output.flush()
            value = terminal.readline()
            if not value:
                raise ValueError('No hostname input received.')
            return value.strip()
    except OSError:
        raise ValueError('Setup needs a terminal. For unattended setup set PT_HOSTNAME (empty for IP) and, optionally, PT_PUBLIC_IP.') from None


def choose_config(saved=None, prompt=False):
    if saved and not prompt and 'PT_HOSTNAME' not in os.environ:
        return site_config(saved['host'], saved['email'])
    value = os.environ['PT_HOSTNAME'] if 'PT_HOSTNAME' in os.environ else prompt_hostname()
    return site_config(value or detect_public_ip(), os.environ.get('PT_ACME_EMAIL', DEFAULT_EMAIL))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt', action='store_true')
    parser.add_argument('--reuse', action='store_true')
    args = parser.parse_args()
    saved_path = Path('/etc/parenting-together-site.json')
    caddy_path = Path('/etc/caddy/Caddyfile')
    saved = json.loads(saved_path.read_text()) if saved_path.exists() else None
    config = choose_config(saved, prompt=args.prompt)
    template = Path(__file__).with_name('Caddyfile.template').read_text()
    rendered = render_config(config, template)
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / 'Caddyfile'
        candidate.write_text(rendered)
        subprocess.run(['caddy', 'validate', '--config', str(candidate), '--adapter', 'caddyfile'], check=True)
    # Validated data only. Certificates themselves stay in Caddy's data directory.
    for path, content in ((caddy_path.with_name('parenting-together-site.caddy'), rendered),
                          (caddy_path, Path(__file__).with_name('Caddyfile').read_text()),
                          (saved_path, json.dumps(config, indent=2) + '\n')):
        temp = path.with_name(path.name + '.pending')
        temp.write_text(content)
        temp.chmod(0o644)
        temp.replace(path)
    # Quarantine only staging certs for the selected host, never trusted certs.
    storage = Path('/var/lib/caddy/.local/share/caddy/certificates')
    staging = storage / 'acme-staging-v02.api.letsencrypt.org-directory' / config['host']
    if staging.is_dir():
        backup = staging.parent.parent.parent / 'staging-certificate-backups'
        backup.mkdir(exist_ok=True, mode=0o700)
        import time
        staging.rename(backup / (config['host'] + '-' + str(time.time_ns())))
    print(config['url'])


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit('Site setup failed: ' + str(error)) from error
