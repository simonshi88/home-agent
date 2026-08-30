from unittest.mock import AsyncMock

from agent.exercise_tool import ExerciseCatalog


async def test_chinese_exercise_names_are_looked_up_as_one_batch() -> None:
    catalog = ExerciseCatalog("postgresql://unused")
    catalog._lookup = AsyncMock(return_value={"data": [], "total": 0})

    await catalog.query_exercises(
        action="search",
        query="核心动作：引体向上、高位下拉、杠铃划船",
    )

    catalog._lookup.assert_awaited_once_with(
        ["引体向上", "高位下拉", "杠铃划船"],
    )


async def test_chinese_back_search_uses_database_body_part() -> None:
    catalog = ExerciseCatalog("postgresql://unused")
    catalog._search = AsyncMock(return_value={"data": [], "total": 0})

    await catalog.query_exercises(action="search", query="我要练背")

    catalog._search.assert_awaited_once_with(
        query=None,
        category=None,
        body_part="back",
        equipment=None,
        target=None,
        limit=10,
    )
