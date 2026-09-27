"""确认创建工单时的失败响应。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.deps import CurrentPlayer
from app.api.v1.chat import TicketConfirmRequest, confirm_ticket_offer


@pytest.mark.asyncio
async def test_confirm_ticket_reports_database_failure():
    checkpoint = SimpleNamespace(checkpoint={"channel_values": {
        "ticket_offer": {"issue_type": "payment", "summary": "未到账"},
        "tool_calls": [],
    }})
    checkpointer = SimpleNamespace(aget_tuple=AsyncMock(return_value=checkpoint))
    append_reply = AsyncMock()

    with patch("app.api.v1.chat.get_checkpointer", new=AsyncMock(return_value=checkpointer)), \
         patch("app.core.checkpoint_helper.append_agent_reply", new=append_reply), \
         patch("app.services.ticket_service.create_ticket_core", return_value={
             "status": "failed", "error": "工单创建失败，请稍后重试。",
         }):
        response = await confirm_ticket_offer(
            TicketConfirmRequest(session_id="player-1_session", confirmed=True),
            CurrentPlayer(user_id="player-1"),
        )

    assert response.status == "failed"
    assert response.ticket_id is None
    assert response.estimated_response is None
    assert "创建失败" in append_reply.await_args.args[1]
