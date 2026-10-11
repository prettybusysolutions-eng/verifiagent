import hashlib
import hmac
import subprocess
import tempfile
import unittest
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import app
from config import settings
from services.report_store import ReportStore
from services.verdict_engine import VerdictEngine

class OperatorBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(settings, 'report_db_path', self.temp.name + '/reports.sqlite'),
                        patch.object(settings, 'api_key_hash', hashlib.sha256(b'operator-secret').hexdigest()),
                        patch.object(settings, 'worker_image', None)]
        for p in self.patches:
            p.start()
        self.client = TestClient(app)
        self.headers = {'X-API-Key': 'operator-secret'}
        self.body = {'repo_url': 'https://github.com/example/project', 'commit_sha': 'a' * 40, 'diff': 'harmless'}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_unauthed_execution_and_reports_rejected(self):
        self.assertEqual(self.client.post('/verify/local', json=self.body).status_code, 401)
        self.assertEqual(self.client.get('/verify/report/not-real').status_code, 401)

    def test_static_report_partial_and_persistent_with_owner_boundary(self):
        response = self.client.post('/verify/local', json=self.body, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report['verdict'], 'PARTIAL')
        owner = hashlib.sha256(b'operator-secret').hexdigest()
        self.assertIsNotNone(ReportStore(settings.report_db_path).get(report['id'], owner))
        self.assertIsNone(ReportStore(settings.report_db_path).get(report['id'], 'other-owner'))

    def test_missing_key_fails_closed(self):
        with patch.object(settings, 'api_key_hash', None):
            self.assertEqual(self.client.post('/verify/local', json=self.body, headers=self.headers).status_code, 503)

    def test_readiness_does_not_invent_worker(self):
        response = self.client.get('/verify/ready')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()['detail']['checks']['isolated_worker'])

    def test_default_webhook_secret_never_bypasses_signature(self):
        with patch.object(settings, 'github_webhook_secret', 'development-secret-change-me'):
            self.assertEqual(self.client.post('/webhooks/github', json={}).status_code, 503)

    def test_signed_webhook_checks_runtime_secret(self):
        body = b'{"action":"created"}'
        secret = 'private-test-secret'
        signature = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with patch.object(settings, 'github_webhook_secret', secret):
            self.assertEqual(self.client.post('/webhooks/github', content=body).status_code, 401)
            response = self.client.post('/webhooks/github', content=body, headers={'X-Hub-Signature-256': signature, 'X-GitHub-Event': 'installation'})
            self.assertEqual(response.status_code, 200)

    def test_interrupted_job_durable_partial(self):
        db = ReportStore(settings.report_db_path)
        job_id = str(uuid.uuid4())
        db.create(job_id, 'owner')
        self.assertTrue(db.start(job_id, 'owner'))
        self.assertFalse(db.start(job_id, 'owner'))
        self.assertEqual(db.recover_interrupted(), 1)
        self.assertEqual(ReportStore(settings.report_db_path).get(job_id, 'owner')['status'], 'PARTIAL')

    def test_git_failure_is_partial(self):
        subprocess.run(['git', 'init', self.temp.name], check=True, capture_output=True)
        engine = VerdictEngine(command_runner=lambda command, path: subprocess.CompletedProcess(command, 0, '', ''))
        report = engine.verify_pr(self.body['repo_url'], 'a'*40, clone_dir=self.temp.name)
        self.assertEqual(report.verdict.value, 'PARTIAL')
        self.assertFalse(report.checks)

    def test_option_injection_denied(self):
        engine = VerdictEngine(command_runner=lambda *a: self.fail('must not execute'))
        report = engine.verify_pr(self.body['repo_url'], '--help', clone_dir=self.temp.name)
        self.assertEqual(report.verdict.value, 'PARTIAL')

    def test_valid_exact_commit_diff_observed_without_false_pass(self):
        from pathlib import Path
        repo = Path(self.temp.name) / 'project'
        repo.mkdir()
        subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Fixture'], check=True)
        subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'fixture@example.invalid'], check=True)
        (repo / 'file.txt').write_text('first\n')
        subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(repo), 'commit', '-m', 'base'], check=True, capture_output=True)
        base = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        (repo / 'file.txt').write_text('second\n')
        subprocess.run(['git', '-C', str(repo), 'commit', '-am', 'head'], check=True, capture_output=True)
        head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        report = VerdictEngine(command_runner=lambda *a: None).verify_pr(self.body['repo_url'], head, clone_dir=repo, base_sha=base)
        self.assertEqual(report.verdict.value, 'PARTIAL')
        self.assertFalse(any('Git preparation' in reason for reason in report.partial_reasons))
        self.assertTrue(report.partial_reasons)

    def test_worker_constraints_and_cleanup_are_mandatory(self):
        from services.isolated_runner import IsolatedRunner
        image = 'worker@sha256:' + 'a'*64
        with patch('services.isolated_runner.shutil.which', return_value='/usr/bin/docker'):
            runner = IsolatedRunner(image)
        with patch('services.isolated_runner.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            runner('python -m unittest', self.temp.name)
            args = run.call_args_list[0].args[0]
            for flag in ('--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--user=65534:65534', '--pull=never'):
                self.assertIn(flag, args)
            self.assertEqual(run.call_args_list[-1].args[0][:3], ['docker', 'rm', '-f'])

    def test_worker_requires_digest(self):
        from services.isolated_runner import IsolatedRunner
        with self.assertRaises(ValueError):
            IsolatedRunner('worker:latest')
