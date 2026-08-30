from __future__ import annotations

import json

import httpx

from agent.paperless_tool import PaperlessAPI, owner_upload_directory


async def test_query_paperless_search_uses_token_and_compacts_documents(
    tmp_path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Token secret-token"
        assert request.url.params["query"] == "保险"
        return httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {"id": 7, "title": "家庭保险", "content": "very long OCR"},
                ],
            },
        )

    api = PaperlessAPI(
        base_url="http://paperless.test",
        api_token="secret-token",
        timeout=5,
        upload_dir=str(tmp_path),
        owner_id="owner-a",
        transport=httpx.MockTransport(handler),
    )

    result = await api.query_paperless(query="保险")

    assert result["count"] == 1
    assert result["data"] == [
        {
            "id": 7,
            "title": "家庭保险",
            "paperless_url": "http://paperless.test/documents/7/details",
        },
    ]


async def test_upload_paperless_document_uses_only_staged_owner_file(tmp_path) -> None:
    upload_id = "d667e1f3-bc97-4c7c-aa64-6bdde68a8081"
    upload_dir = owner_upload_directory(str(tmp_path), "owner-a") / upload_id
    upload_dir.mkdir(parents=True)
    (upload_dir / "invoice.pdf").write_bytes(b"pdf-content")
    (upload_dir / "metadata.json").write_text(
        json.dumps(
            {
                "filename": "invoice.pdf",
                "content_type": "application/pdf",
                "size": 11,
            },
        ),
        encoding="utf-8",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        assert request.url.path == "/api/documents/post_document/"
        assert b'invoice.pdf' in body
        assert b'paper invoice' in body
        return httpx.Response(200, json="task-123")

    api = PaperlessAPI(
        base_url="http://paperless.test",
        api_token="secret-token",
        timeout=5,
        upload_dir=str(tmp_path),
        owner_id="owner-a",
        transport=httpx.MockTransport(handler),
    )

    result = await api.upload_paperless_document(upload_id, title="paper invoice")

    assert result["task_id"] == "task-123"
    assert not upload_dir.exists()
