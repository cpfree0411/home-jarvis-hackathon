#!/usr/bin/env python3
"""Install the built wheel into a fresh venv and run it away from the checkout."""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    wheels = list((ROOT / 'dist').glob('*.whl'))
    if len(wheels) != 1:
        sys.exit('Build exactly one wheel with python -m build first.')
    wheel = wheels[0]
    checks = []

    def check(name, ok):
        checks.append({'name': name, 'pass': bool(ok)})
        print(('PASS ' if ok else 'FAIL ') + name)

    with zipfile.ZipFile(wheel) as z:
        names = z.namelist()
        check('wheel contains eight original samples', sum('/web/art/' in n and n.endswith('.svg') for n in names) == 8)
        check('wheel includes public evidence fixture', any(n.endswith('/data/fixtures/wikipedia-snapshots.json') for n in names))
        check('wheel includes licenses and notices', all(any(n.endswith('/' + suffix) for n in names) for suffix in ['LICENSE', 'NOTICE', 'CC0-1.0.txt', 'CC-BY-SA-4.0.txt']))
        check('wheel excludes private env, caches and local media', not any('.env' in n or '/media/' in n or n.endswith('.pyc') for n in names))
    with tempfile.TemporaryDirectory(prefix='otaku-install-') as temporary:
        work = Path(temporary)
        venv = work / 'env'
        subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True, capture_output=True)
        subprocess.run([str(venv / 'bin/python'), '-m', 'pip', 'install', '--no-deps', str(wheel)], check=True, capture_output=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        environment = {'HOME': str(work), 'PATH': '/usr/bin:/bin', 'OTAKU_HOST': '127.0.0.1',
                       'OTAKU_PORT': str(port), 'OTAKU_EVIDENCE_MODE': 'fixture', 'OTAKU_LOG_LEVEL': 'ERROR'}
        process = subprocess.Popen([str(venv / 'bin/otaku-gallery')], cwd=work, env=environment,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def call(method, path, value=None):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            data = json.dumps(value).encode() if value is not None else None
            headers = {'Content-Type': 'application/json'} if data else {}
            connection.request(method, path, data, headers)
            response = connection.getresponse()
            body = response.read()
            connection.close()
            return response.status, body

        try:
            for _ in range(80):
                try:
                    status, body = call('GET', '/health')
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError('Installed command exited before health became ready.')
                    time.sleep(.1)
            else:
                raise RuntimeError('Installed server did not become healthy.')
            health = json.loads(body)
            check('installed command starts with isolated environment', status == 200 and health['ok'])
            check('installed gallery loads without checkout or key', health['artworks'] == 8 and not health['nebius_configured'])
            check('installed index is English', b'lang="en"' in call('GET', '/')[1])
            items = json.loads(call('GET', '/api/gallery')[1])['items']
            check('installed artwork files all served', all(call('GET', '/' + i['url'])[0] == 200 for i in items))
            check('installed browser code all served', all(call('GET', '/' + n)[0] == 200 for n in ['app.js', 'app.css', 'research.js', 'research.css', 'strings.js', 'favicon.svg']))
            view = json.loads(call('POST', '/api/research', {'query': 'Cyberpunk'})[1])
            for _ in range(60):
                if view['status'] not in ('queued', 'running'):
                    break
                time.sleep(.1)
                view = json.loads(call('GET', '/api/research/' + view['id'])[1])
            check('installed no-key research uses source excerpts', view.get('page', {}).get('status') == 'evidence_only' and bool(view['page']['sources']))
        finally:
            process.terminate()
            process.wait(timeout=10)
    result = {'wheel': wheel.name, 'checks': checks, 'passed': sum(c['pass'] for c in checks), 'total': len(checks),
              'environment': 'fresh venv, unrelated working directory, empty inherited environment, explicit minimal PATH', 'paid_calls': 0}
    path = ROOT / 'docs/validation/install.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('%d/%d checks passed' % (result['passed'], result['total']))
    return 0 if all(c['pass'] for c in checks) else 1


if __name__ == '__main__':
    sys.exit(main())
