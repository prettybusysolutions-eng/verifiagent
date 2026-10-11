"""Resource-limited Docker execution. No host fallback is permitted."""
import re
import shutil
import subprocess
from pathlib import Path


class IsolatedRunner:
    def __init__(self, image):
        if not image or not re.fullmatch(r'[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}', image):
            raise ValueError('Worker image must be pinned by SHA256 digest')
        if not shutil.which('docker'):
            raise OSError('Docker worker unavailable')
        self.image = image

    def __call__(self, command, project_path):
        path = Path(project_path).resolve(strict=True)
        if not path.is_dir() or ',' in str(path):
            raise ValueError('Invalid checkout path')
        name = 'verifiagent-' + __import__('uuid').uuid4().hex
        args = ['docker', 'run', '--name', name, '--pull=never', '--rm', '--network=none',
                '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                '--pids-limit=128', '--memory=512m', '--cpus=1', '--user=65534:65534',
                '--mount', f'type=bind,src={path},dst=/source,readonly',
                '--tmpfs', '/work:rw,nosuid,nodev,size=268435456,mode=1777',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=67108864,mode=1777',
                '--workdir=/work', self.image, 'sh', '-c',
                'cp -R /source/. /work/ && ' + command]
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=120)
        finally:
            # docker client termination alone does not stop its container.
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=15)
