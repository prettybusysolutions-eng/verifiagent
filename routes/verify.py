"""Authenticated operator API; PR execution requires a constrained worker."""
import hashlib
import hmac
import shutil
import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Request
from models.verification import VerificationReport, VerificationRequest
from services.verdict_engine import VerdictEngine
from services.report_store import ReportStore
from services.isolated_runner import IsolatedRunner
from config import settings

router = APIRouter(prefix='/verify', tags=['verification'])

def store():
    return ReportStore(settings.report_db_path)

async def require_operator(request: Request):
    expected = settings.api_key_hash
    if not expected:
        raise HTTPException(503, 'Operator key hash not configured')
    supplied = request.headers.get(settings.api_key_header, '')
    actual = hashlib.sha256(supplied.encode()).hexdigest()
    if not supplied or not hmac.compare_digest(actual, expected):
        raise HTTPException(401, 'Invalid operator credentials')
    return actual

@router.post('/local', response_model=VerificationReport)
async def verify_local(request: VerificationRequest, owner: str = Depends(require_operator)):
    if not request.diff:
        raise HTTPException(400, 'diff is required')
    report = VerdictEngine().verify_local(request.diff, request.language or 'python', request.surface or 'api')
    db = store()
    db.create(str(report.id), owner)
    db.finish(str(report.id), owner, report)
    return report

@router.post('/pr')
async def verify_pr(request: VerificationRequest, background_tasks: BackgroundTasks, owner: str = Depends(require_operator)):
    if not request.pr_url or not request.base_sha:
        raise HTTPException(400, 'pr_url and exact base_sha are required')
    if request.repo_url not in settings.allowed_repositories:
        raise HTTPException(403, 'Repository not admitted')
    try:
        IsolatedRunner(settings.worker_image)
    except (ValueError, OSError):
        raise HTTPException(503, 'Pinned isolated worker is not configured or unavailable')
    report_id = str(uuid.uuid4())
    db = store()
    db.create(report_id, owner)
    def run_verification():
        if not db.start(report_id, owner):
            return
        try:
            report = VerdictEngine().verify_pr(request.repo_url, request.commit_sha, request.pr_url,
                        request.language or 'python', request.surface or 'api', base_sha=request.base_sha)
            report.id = uuid.UUID(report_id)
        except Exception:
            report = VerificationReport(id=report_id, partial_reasons=['Worker failed before complete evidence'])
            report.final_verdict()
        db.finish(report_id, owner, report)
    background_tasks.add_task(run_verification)
    return {'report_id': report_id, 'status': 'QUEUED', 'poll_url': '/verify/report/' + report_id}

@router.get('/report/{report_id}')
async def get_report(report_id: str, owner: str = Depends(require_operator)):
    result = store().get(report_id, owner)
    if result is None:
        raise HTTPException(404, 'Report not found')
    return result

@router.get('/health')
async def health():
    return {'status': 'ok', 'service': 'VerifiAgent', 'version': settings.version}

@router.get('/ready')
async def ready():
    checks = {'database': False, 'operator_auth': bool(settings.api_key_hash), 'isolated_worker': False,
              'repository_allowlist': bool(settings.allowed_repositories)}
    try:
        checks['database'] = store().healthy()
        IsolatedRunner(settings.worker_image)
        import subprocess
        checks['isolated_worker'] = subprocess.run(['docker', 'image', 'inspect', settings.worker_image], capture_output=True, timeout=5).returncode == 0
    except (OSError, ValueError, __import__('subprocess').TimeoutExpired):
        pass
    if not all(checks.values()):
        raise HTTPException(503, {'status': 'not_ready', 'checks': checks})
    return {'status': 'ready', 'checks': checks}
