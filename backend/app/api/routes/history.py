from fastapi import APIRouter, Request

from ...core.errors import AppError, ErrorCode
from ...schemas.history import HistoryItemOut, HistoryListResponse, OpenHistoryRequest

router = APIRouter(prefix="/api/history", tags=["history"])


def _history(request: Request):
    return request.app.state.history_service


@router.get("", response_model=HistoryListResponse)
def list_history(request: Request, limit: int = 50) -> HistoryListResponse:
    items = _history(request).list(limit=limit)
    return HistoryListResponse(items=[HistoryItemOut(**item.to_dict()) for item in items])


@router.get("/{item_id}", response_model=HistoryItemOut)
def get_history_item(item_id: str, request: Request) -> HistoryItemOut:
    item = _history(request).get(item_id)
    if not item:
        raise AppError(ErrorCode.NOT_FOUND, "That history item was not found.", status_code=404)
    return HistoryItemOut(**item.to_dict())


@router.delete("/{item_id}")
def delete_history_item(item_id: str, request: Request) -> dict:
    success = _history(request).delete(item_id)
    if not success:
        raise AppError(ErrorCode.NOT_FOUND, "That history item was not found.", status_code=404)
    return {"deleted": True, "id": item_id}


@router.post("/{item_id}/open")
def open_history_file(item_id: str, body: OpenHistoryRequest, request: Request) -> dict:
    path = _history(request).completed_file(item_id)
    request.app.state.opener(path, select=(body.action == "folder"))
    return {"opened": True}
