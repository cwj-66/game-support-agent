"""工单归属与创建结果的回归测试。"""

from types import SimpleNamespace
from unittest.mock import patch

from app.services.ticket_service import check_ticket_core, create_ticket_core


def test_check_ticket_own_ticket():
    ticket = SimpleNamespace(
        ticket_id="TK-1", player_uid="player-1", title="充值问题",
        description="未到账", status="processing", priority="P0",
        created_at="2026-09-27", resolved_at=None, agent_reply=None,
        human_reviewed=False,
    )
    with patch("app.repositories.database.get_ticket", return_value=ticket) as get_ticket:
        result = check_ticket_core("player-1", "TK-1")

    get_ticket.assert_called_once_with("TK-1")
    assert result["found"] is True
    assert result["ticket_id"] == "TK-1"
    assert result["description"] == "未到账"


def test_check_ticket_other_players_ticket_is_hidden():
    ticket = SimpleNamespace(ticket_id="TK-2", player_uid="player-2")
    with patch("app.repositories.database.get_ticket", return_value=ticket):
        result = check_ticket_core("player-1", "TK-2")

    assert result["found"] is False
    assert result["status"] == "not_found"
    assert "description" not in result
    assert "agent_reply" not in result


def test_create_ticket_succeeds_only_with_database_ticket():
    with patch("app.repositories.database.create_ticket", return_value=SimpleNamespace(ticket_id="TK-3")) as create:
        result = create_ticket_core("player-1", "payment", "未到账")

    create.assert_called_once_with(
        player_uid="player-1", title="充值/退款问题", description="未到账", priority="P0"
    )
    assert result["status"] == "submitted"
    assert result["ticket_id"] == "TK-3"
    assert result["_health"]["ok"] is True


def test_create_ticket_database_failure_has_no_ticket_id():
    with patch("app.repositories.database.create_ticket", side_effect=RuntimeError("数据库不可用")):
        result = create_ticket_core("player-1", "payment", "未到账")

    assert result["status"] == "failed"
    assert result["_health"]["ok"] is False
    assert "ticket_id" not in result
    assert "estimated_response" not in result


def test_create_ticket_without_persisted_ticket_id_fails():
    with patch("app.repositories.database.create_ticket", return_value=SimpleNamespace(ticket_id=None)):
        result = create_ticket_core("player-1", "payment", "未到账")

    assert result["status"] == "failed"
    assert "ticket_id" not in result
