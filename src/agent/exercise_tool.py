"""Read-only access to the exercise catalog stored in PostgreSQL."""

from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

_COLUMNS = """
id, name, category, body_part, equipment, instructions, instruction_steps,
muscle_group, secondary_muscles, target, media_id, image_path, gif_path,
attribution, source_created_at
"""

_ZH_EXERCISE_ALIASES: dict[str, tuple[str, ...]] = {
    "引体向上": ("pull-up", "pull up", "chin-up"),
    "高位下拉": ("lat pulldown", "pulldown"),
    "杠铃划船": ("barbell bent over row", "barbell row"),
    "坐姿划船": ("seated row",),
    "单臂哑铃划船": ("dumbbell one arm bent-over row", "one arm dumbbell row"),
    "直臂下压": ("straight arm pulldown", "straight-arm pulldown"),
    "俯身飞鸟": ("dumbbell reverse fly", "reverse fly"),
}


def _serializable(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    value = row.get("source_created_at")
    if hasattr(value, "isoformat"):
        row["source_created_at"] = value.isoformat()
    return row


class ExerciseCatalog:
    """Create an AgentScope tool that can only read ``exercise_catalog``."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    async def query_exercises(
        self,
        action: Literal["search", "get", "facets", "lookup"] = "search",
        query: str | None = None,
        exercise_names: list[str] | None = None,
        exercise_id: str | None = None,
        category: str | None = None,
        body_part: str | None = None,
        equipment: str | None = None,
        target: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """查询动作数据库。

        Args:
            action: search 搜索，lookup 批量查动作，get 按 ID 获取，facets 获取筛选项。
            query: 按动作名、目标肌肉、器械或肌群模糊搜索。
            exercise_names: lookup 时传入中文或英文动作名，最多 20 个。
            exercise_id: get 时必填的四位动作 ID。
            category: 动作类别筛选。
            body_part: 身体部位筛选。
            equipment: 器械筛选。
            target: 目标肌肉筛选。
            limit: search 返回数量，范围 1 到 20。
        """
        if action == "get":
            return await self._get(exercise_id)
        if action == "facets":
            return await self._facets()
        if action == "lookup":
            return await self._lookup(exercise_names)
        if action != "search":
            raise ValueError("action must be search, lookup, get, or facets")
        aliases = _aliases_in_query(query)
        if aliases:
            return await self._lookup(aliases)
        if query and any(word in query for word in ("背部", "练背")):
            query = None
            body_part = body_part or "back"
        return await self._search(
            query=query,
            category=category,
            body_part=body_part,
            equipment=equipment,
            target=target,
            limit=limit,
        )

    async def _lookup(self, names: list[str] | None) -> dict[str, Any]:
        if not names or len(names) > 20:
            raise ValueError("exercise_names must contain between 1 and 20 names")
        groups: list[dict[str, Any]] = []
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                for requested_name in names:
                    requested_name = str(requested_name).strip()[:80]
                    terms = _ZH_EXERCISE_ALIASES.get(
                        requested_name,
                        (requested_name,),
                    )
                    clauses = " OR ".join("name ILIKE %s" for _ in terms)
                    patterns = [f"%{term}%" for term in terms]
                    await cursor.execute(
                        f"SELECT {_COLUMNS} FROM exercise_catalog "
                        f"WHERE {clauses} ORDER BY length(name), name ASC LIMIT 3",
                        patterns,
                    )
                    groups.append(
                        {
                            "requested_name": requested_name,
                            "matches": [
                                _serializable(row) for row in await cursor.fetchall()
                            ],
                        },
                    )
        return {"data": groups, "total": sum(len(x["matches"]) for x in groups)}

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self.database_url,
            row_factory=dict_row,
            autocommit=True,
        )

    async def _get(self, exercise_id: str | None) -> dict[str, Any]:
        if not exercise_id or len(exercise_id) != 4 or not exercise_id.isdigit():
            raise ValueError("exercise_id must be exactly four digits")
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT {_COLUMNS} FROM exercise_catalog WHERE id = %s",
                    (exercise_id,),
                )
                row = await cursor.fetchone()
        return {"data": _serializable(row)}

    async def _search(self, **filters: Any) -> dict[str, Any]:
        limit = filters.pop("limit")
        if not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        clauses: list[str] = []
        values: list[Any] = []
        query = filters.pop("query")
        if query:
            values.append(f"%{str(query)[:120]}%")
            clauses.append(
                "(name ILIKE %s OR target ILIKE %s OR equipment ILIKE %s "
                "OR muscle_group ILIKE %s)"
            )
            values.extend([values[-1]] * 3)
        columns = {
            "category": "category",
            "body_part": "body_part",
            "equipment": "equipment",
            "target": "target",
        }
        for key, column in columns.items():
            if value := filters.get(key):
                clauses.append(f"{column} ILIKE %s")
                values.append(f"%{str(value)[:80]}%")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT count(*) AS total FROM exercise_catalog{where}", values
                )
                total_row = await cursor.fetchone()
                await cursor.execute(
                    f"SELECT {_COLUMNS} FROM exercise_catalog{where} "
                    "ORDER BY name ASC LIMIT %s",
                    [*values, limit],
                )
                rows = await cursor.fetchall()
        return {
            "data": [_serializable(row) for row in rows],
            "total": int((total_row or {}).get("total", 0)),
        }

    async def _facets(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        columns = {
            "categories": "category",
            "body_parts": "body_part",
            "equipment": "equipment",
            "targets": "target",
        }
        async with await self._connect() as connection:
            async with connection.cursor() as cursor:
                for key, column in columns.items():
                    await cursor.execute(
                        f"SELECT DISTINCT {column} AS value FROM exercise_catalog "
                        "WHERE " + column + " <> '' ORDER BY value"
                    )
                    result[key] = [row["value"] for row in await cursor.fetchall()]
        return result


def build_exercise_tool(database_url: str) -> Any:
    """Build the single read-only exercise catalog tool."""
    from agentscope.tool import FunctionTool

    catalog = ExerciseCatalog(database_url)
    return FunctionTool(catalog.query_exercises, is_read_only=True)


def _aliases_in_query(query: str | None) -> list[str]:
    if not query:
        return []
    return [name for name in _ZH_EXERCISE_ALIASES if name in query]
