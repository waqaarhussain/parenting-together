import json
import os
import pty
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.configure_site import detect_public_ip, choose_config, normalize_host, render_config, site_config

TEMPLATE = Path('deploy/Caddyfile.template').read_text()


class SiteConfiguration(unittest.TestCase):
    def test_hostname_and_pasted_url(self):
        self.assertEqual(normalize_host(' https://App.Example.com/ '), ('app.example.com', 'hostname'))
        config=site_config('app.example.com')
        self.assertEqual(config['url'],'https://app.example.com')
        rendered=render_config(config,TEMPLATE)
        self.assertIn('https://app.example.com {',rendered)
        self.assertNotIn('shortlived',rendered)
        self.assertNotIn('@@',rendered)

    def test_blank_uses_public_ip_and_production_shortlived_certificates(self):
        with patch.dict(os.environ, {'PT_HOSTNAME':'','PT_PUBLIC_IP':'93.184.216.34'}, clear=True):
            config=choose_config()
        self.assertEqual(config['mode'],'ip')
        self.assertEqual(config['url'],'https://93.184.216.34')
        rendered=render_config(config,TEMPLATE)
        self.assertIn('default_sni 93.184.216.34',rendered)
        self.assertIn('profile shortlived',rendered)
        self.assertNotIn('staging',rendered)
        self.assertNotIn('zerossl',rendered)
        self.assertNotIn('tls internal',rendered)

    def test_ip_detection_skips_address_entries_without_local_field(self):
        interfaces=[{'addr_info':[{'family':'inet','local':'79.99.40.230'},
                                 {'family':'inet6','scope':'global'}, None]},
                    {'ifname':'extra','addr_info':None}]
        with patch.dict(os.environ,{},clear=True), patch('deploy.configure_site.subprocess.check_output',return_value=json.dumps(interfaces).encode()):
            self.assertEqual(detect_public_ip(),'79.99.40.230')

    def test_ip_detection_uses_external_lookup_when_no_usable_interface_address(self):
        interfaces=[{'addr_info':[{'family':'inet6'}, {'local':'10.0.0.2'}, {'local':None}]}]
        with patch.dict(os.environ,{},clear=True), patch('deploy.configure_site.subprocess.check_output',return_value=json.dumps(interfaces).encode()), patch('deploy.configure_site.urlopen') as lookup:
            lookup.return_value.__enter__.return_value.read.return_value=b'79.99.40.230'
            self.assertEqual(detect_public_ip(),'79.99.40.230')
            lookup.assert_called_once()

    def test_ipv6_url_is_bracketed(self):
        config=site_config('2606:4700:4700::1111')
        self.assertEqual(config['url'],'https://[2606:4700:4700::1111]')
        self.assertIn(config['url']+' {',render_config(config,TEMPLATE))

    def test_updates_reuse_saved_selection_without_prompting_or_redetection(self):
        saved=site_config('app.example.com')
        with patch.dict(os.environ, {}, clear=True), patch('deploy.configure_site.prompt_hostname',side_effect=AssertionError('unexpected prompt')):
            self.assertEqual(choose_config(saved),saved)

    def test_explicit_blank_overrides_a_saved_hostname(self):
        with patch.dict(os.environ, {'PT_HOSTNAME':'','PT_PUBLIC_IP':'93.184.216.34'}, clear=True):
            config=choose_config(site_config('app.example.com'))
        self.assertEqual(config['mode'],'ip')

    def test_rejects_private_ips_invalid_hosts_and_config_injection(self):
        for value in ['127.0.0.1','192.168.1.5','10.0.0.1','::1','fc00::1','foo.local','*',
                      'example.com\n{\nrespond secret','example.com:443','https://example.com/other',
                      'http://user:password@example.com','app.example.com?x=1','example.com;id']:
            with self.subTest(value=value),self.assertRaises(ValueError):normalize_host(value)
        with self.assertRaises(ValueError):site_config('app.example.com','bad@example.com\nrespond secret')

    def test_bootstrap_prompt_uses_tty_even_when_stdin_is_a_script_pipe(self):
        # Like curl | bash: the program's stdin is not the user's terminal.
        pid,fd=pty.fork()
        if pid==0:
            code="import json; from deploy.configure_site import prompt_hostname; print('ANSWER='+json.dumps(prompt_hostname()))"
            os.execv(sys.executable,[sys.executable,'-c',code])
        output=b''
        try:
            for _ in range(30):
                if select.select([fd],[],[],.2)[0]:
                    output+=os.read(fd,4096)
                if b'HTTPS): ' in output:break
            self.assertIn(b'HTTPS): ',output)
            os.write(fd,b'app.example.com\n')
            for _ in range(30):
                if select.select([fd],[],[],.2)[0]:
                    try:output+=os.read(fd,4096)
                    except OSError:break
                if b'ANSWER=' in output:break
            self.assertIn(b'ANSWER="app.example.com"',output)
        finally:
            os.close(fd)
            os.waitpid(pid,0)
