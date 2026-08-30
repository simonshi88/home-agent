"""Capability-scoped Paperless-ngx API tools."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx


def owner_upload_directory(root: str, owner_id: str) -> Path:
    """Return a non-identifying, owner-scoped staging directory."""
    owner_key = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:24]
    return Path(root) / owner_key


def resolve_staged_upload(
    root: str,
    owner_id: str,
    upload_id: str,
) -> tuple[Path, dict[str, str]]:
    """Resolve only UUID-named files previously staged by the authenticated web API."""
    try:
        normalized_id = str(UUID(upload_id))
    except ValueError as exc:
        raise ValueError("upload_id is invalid") from exc
    upload_dir = owner_upload_directory(root, owner_id) / normalized_id
    metadata_path = upload_dir / "metadata.json"
    if not metadata_path.is_file():
        raise ValueError("upload_id was not found or has expired")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    filename = metadata.get("filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ValueError("staged upload metadata is invalid")
    document_path = upload_dir / filename
    if not document_path.is_file():
        raise ValueError("staged document is missing")
    return document_path, metadata


class PaperlessAPI:
    """Small Paperless client exposed to one specialist Agent only."""

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str | None,
        timeout: float,
        upload_dir: str,
        owner_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout
        self.upload_dir = upload_dir
        self.owner_id = owner_id
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        if not self.api_token:
            raise RuntimeError(
                "Paperless is not configured: PAPERLESS_API_TOKEN is missing",
            )
        return {
            "Authorization": f"Token {self.api_token}",
            "Accept": "application/json",
        }

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers(),
            timeout=self.timeout,
            transport=self.transport,
            trust_env=False,
        ) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    async def query_paperless(
        self,
        action: str = "search",
        query: str | None = None,
        document_id: int | None = None,
        task_id: str | None = None,
        page: int = 1,
        page_size: int = 10,
        ordering: str = "-created",
    ) -> dict[str, Any]:
        """查询 Paperless-ngx 文档和常用分类信息。

        Args:
            action: search 搜索文档；get 取详情；tags、correspondents、
                document_types、storage_paths、custom_fields 列出分类；task 查上传任务。
            query: search 时的全文搜索词，可留空列出最近文档。
            document_id: get 时必填的文档数字 ID。
            task_id: task 时必填的上传任务 UUID。
            page: 分页页码，从 1 开始。
            page_size: 每页数量，范围 1 到 25。
            ordering: 文档排序，默认按创建时间倒序。
        """
        if page < 1 or not 1 <= page_size <= 25:
            raise ValueError("page must be >= 1 and page_size must be between 1 and 25")
        if action == "get":
            if not isinstance(document_id, int) or document_id <= 0:
                raise ValueError("document_id must be a positive integer")
            payload = await self._get(f"/api/documents/{document_id}/")
            if isinstance(payload, dict) and isinstance(payload.get("content"), str):
                payload["content"] = payload["content"][:12_000]
                payload["paperless_url"] = (
                    f"{self.base_url}/documents/{document_id}/details"
                )
            return {"data": payload}
        if action == "task":
            if not task_id:
                raise ValueError("task_id is required")
            return {"data": await self._get("/api/tasks/", {"task_id": task_id})}
        resources = {
            "tags": "tags",
            "correspondents": "correspondents",
            "document_types": "document_types",
            "storage_paths": "storage_paths",
            "custom_fields": "custom_fields",
        }
        if action in resources:
            payload = await self._get(
                f"/api/{resources[action]}/",
                {"page": page, "page_size": page_size, "ordering": "name"},
            )
            return _compact_page(payload)
        if action != "search":
            raise ValueError("unsupported Paperless query action")
        params: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "ordering": ordering[:40],
        }
        if query:
            params["query"] = query[:300]
        page_payload = _compact_page(await self._get("/api/documents/", params))
        page_payload["data"] = [
            _compact_document(item, self.base_url)
            for item in page_payload["data"]
            if isinstance(item, dict)
        ]
        return page_payload

    async def upload_paperless_document(
        self,
        upload_id: str,
        title: str | None = None,
        created: str | None = None,
        correspondent_id: int | None = None,
        document_type_id: int | None = None,
        storage_path_id: int | None = None,
        tag_ids: list[int] | None = None,
        archive_serial_number: int | None = None,
    ) -> dict[str, Any]:
        """把网页已暂存的文件上传到 Paperless-ngx。

        Args:
            upload_id: 网页选择文件后生成的上传 UUID，不是任意文件路径。
            title: 可选文档标题。
            created: 可选创建时间，使用 ISO 8601 格式。
            correspondent_id: 可选通讯者 ID。
            document_type_id: 可选文档类型 ID。
            storage_path_id: 可选存储路径 ID。
            tag_ids: 可选标签 ID 列表。
            archive_serial_number: 可选归档序号。
        """
        document_path, metadata = resolve_staged_upload(
            self.upload_dir,
            self.owner_id,
            upload_id,
        )
        form: dict[str, Any] = {}
        optional = {
            "title": title,
            "created": created,
            "correspondent": correspondent_id,
            "document_type": document_type_id,
            "storage_path": storage_path_id,
            "archive_serial_number": archive_serial_number,
        }
        form.update(
            {key: str(value) for key, value in optional.items() if value is not None},
        )
        if tag_ids:
            form["tags"] = [str(tag_id) for tag_id in tag_ids]
        media_type = metadata.get("content_type") or mimetypes.guess_type(
            document_path.name,
        )[0]
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers(),
            timeout=self.timeout,
            transport=self.transport,
            trust_env=False,
        ) as client:
            with document_path.open("rb") as document:
                response = await client.post(
                    "/api/documents/post_document/",
                    data=form,
                    files={
                        "document": (
                            metadata["filename"],
                            document,
                            media_type or "application/octet-stream",
                        ),
                    },
                )
            response.raise_for_status()
            try:
                task_id = response.json()
            except json.JSONDecodeError:
                task_id = response.text.strip().strip('"')
        document_path.unlink(missing_ok=True)
        (document_path.parent / "metadata.json").unlink(missing_ok=True)
        document_path.parent.rmdir()
        return {
            "status": "accepted",
            "task_id": task_id,
            "message": (
                "Paperless 已接收文件，文档仍在异步处理；"
                "请用 task 查询处理结果。"
            ),
        }


def _compact_page(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"data": payload}
    results = payload.get("results", [])
    return {
        "count": payload.get("count", len(results) if isinstance(results, list) else 0),
        "next": payload.get("next"),
        "previous": payload.get("previous"),
        "data": results,
    }


def _compact_document(document: dict[str, Any], base_url: str) -> dict[str, Any]:
    keys = (
        "id",
        "title",
        "created",
        "modified",
        "added",
        "archive_serial_number",
        "correspondent",
        "document_type",
        "storage_path",
        "tags",
        "original_file_name",
    )
    compact = {key: document.get(key) for key in keys if key in document}
    if document_id := document.get("id"):
        compact["paperless_url"] = f"{base_url}/documents/{document_id}/details"
    return compact


def build_paperless_tools(settings: Any, owner_id: str) -> list[Any]:
    """Build read and write tools for the Paperless specialist."""
    from agentscope.tool import FunctionTool

    api = PaperlessAPI(
        base_url=settings.paperless_url,
        api_token=settings.paperless_api_token,
        timeout=settings.paperless_timeout,
        upload_dir=settings.paperless_upload_dir,
        owner_id=owner_id,
    )
    return [
        FunctionTool(api.query_paperless, is_read_only=True),
        FunctionTool(api.upload_paperless_document, is_read_only=False),
    ]
