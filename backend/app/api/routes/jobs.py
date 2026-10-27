from fastapi import APIRouter, Request

from ...schemas.job import (
    BatchItem,
    BatchRequest,
    BatchResponse,
    CreateJobRequest,
    CreateJobResponse,
    JobList,
    JobOut,
    OpenRequest,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _service(request: Request):
    return request.app.state.job_service


@router.post("", response_model=CreateJobResponse, status_code=202)
def create_job(body: CreateJobRequest, request: Request) -> CreateJobResponse:
    job = _service(request).create(body.url, body.format_id, body.output_format)
    return CreateJobResponse(job_id=job.id, status=job.status.value)


@router.post("/batch", response_model=BatchResponse)
def create_batch(body: BatchRequest, request: Request) -> BatchResponse:
    """Queue many links at once (best quality or audio only). Per-link results are returned."""
    results = _service(request).create_batch(body.urls, body.mode)
    items = [BatchItem(**r) for r in results]
    queued = sum(1 for i in items if i.ok)
    return BatchResponse(items=items, queued=queued, failed=len(items) - queued)


@router.post("/{job_id}/retry", response_model=CreateJobResponse, status_code=202)
def retry_job(job_id: str, request: Request) -> CreateJobResponse:
    job = _service(request).retry(job_id)
    return CreateJobResponse(job_id=job.id, status=job.status.value)


@router.get("", response_model=JobList)
def list_jobs(request: Request) -> JobList:
    return JobList(jobs=[JobOut(**j.snapshot()) for j in _service(request).list()])


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, request: Request) -> JobOut:
    return JobOut(**_service(request).get(job_id).snapshot())


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, request: Request) -> JobOut:
    return JobOut(**_service(request).cancel(job_id).snapshot())


@router.post("/{job_id}/open")
def open_job_output(job_id: str, body: OpenRequest, request: Request) -> dict:
    # The path comes from the server's own job record, never from the client.
    path = _service(request).completed_file(job_id)
    request.app.state.opener(path, select=(body.action == "folder"))
    return {"opened": True}
