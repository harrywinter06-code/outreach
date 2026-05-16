import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from clawbot.board import (
    BoardVotingSystem, BoardVote, BoardResolution, SHAREHOLDERS,
    QuorumNotReached, QUORUM_MIN_VOTES,
)


def make_board() -> BoardVotingSystem:
    board = BoardVotingSystem(redis_url="redis://localhost:6379/0")
    mock = MagicMock()
    mock.set = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.exists = AsyncMock(return_value=False)
    mock.publish = AsyncMock()
    mock.aclose = AsyncMock()
    board._redis = mock  # type: ignore[assignment]
    return board


@pytest.mark.asyncio
async def test_submit_vote_writes_to_redis():
    board = make_board()
    vote = BoardVote(
        shareholder_id="shareholder-activist",
        vote="PIVOT",
        rationale="Revenue flat for 4 days",
    )
    await board.submit_vote(vote)
    board._redis.set.assert_called_once()
    call_args = board._redis.set.call_args
    assert "shareholder-activist" in call_args[0][0]
    assert "PIVOT" in call_args[0][1]


@pytest.mark.asyncio
async def test_majority_continue_resolves_continue():
    board = make_board()
    votes = [
        BoardVote("shareholder-activist", "CONTINUE", "Growing"),
        BoardVote("shareholder-conservative", "CONTINUE", "Revenue positive"),
        BoardVote("shareholder-diversifier", "CONTINUE", "Allocation fine"),
        BoardVote("shareholder-longterm", "PIVOT", "No assets"),
        BoardVote("shareholder-opportunist", "PIVOT", "New opportunity"),
    ]
    votes_json = {
        f"clawbot:board:votes:2026-05-15:{v.shareholder_id}": v.to_json()
        for v in votes
    }

    async def mock_get(key):
        return votes_json.get(key)

    board._redis.get = mock_get
    resolution = await board.tally_votes("2026-05-15")
    assert resolution.outcome == "CONTINUE"
    assert not resolution.requires_ceo_action


@pytest.mark.asyncio
async def test_majority_pivot_resolves_pivot_with_ceo_action():
    board = make_board()
    votes = [
        BoardVote("shareholder-activist", "PIVOT", "Slow growth"),
        BoardVote("shareholder-conservative", "PIVOT", "Zero revenue 6 days"),
        BoardVote("shareholder-diversifier", "PIVOT", "Over-concentrated"),
        BoardVote("shareholder-longterm", "CONTINUE", "Content pipeline ok"),
        BoardVote("shareholder-opportunist", "CONTINUE", "No urgent opportunity"),
    ]
    votes_json = {
        f"clawbot:board:votes:2026-05-15:{v.shareholder_id}": v.to_json()
        for v in votes
    }

    async def mock_get(key):
        return votes_json.get(key)

    board._redis.get = mock_get
    resolution = await board.tally_votes("2026-05-15")
    assert resolution.outcome == "PIVOT"
    assert resolution.requires_ceo_action
    assert "24 hours" in resolution.action_required


@pytest.mark.asyncio
async def test_tie_breaks_to_pivot():
    board = make_board()
    # 2 CONTINUE, 2 PIVOT, 1 RESET — no majority
    votes = [
        BoardVote("shareholder-activist", "PIVOT", ""),
        BoardVote("shareholder-conservative", "CONTINUE", ""),
        BoardVote("shareholder-diversifier", "RESET", ""),
        BoardVote("shareholder-longterm", "CONTINUE", ""),
        BoardVote("shareholder-opportunist", "PIVOT", ""),
    ]
    votes_json = {
        f"clawbot:board:votes:2026-05-15:{v.shareholder_id}": v.to_json()
        for v in votes
    }

    async def mock_get(key):
        return votes_json.get(key)

    board._redis.get = mock_get
    resolution = await board.tally_votes("2026-05-15")
    assert resolution.outcome == "PIVOT"  # tie-break: caution


@pytest.mark.asyncio
async def test_emergency_trigger_fires_on_flat_revenue():
    board = make_board()
    triggered = await board.check_emergency_triggers({
        "revenue_flat_days": 3,
        "strategy_unchanged_days": 1,
    })
    assert triggered is True
    board._redis.publish.assert_called_once()
    call_args = board._redis.publish.call_args
    assert "clawbot:board:emergency" in call_args[0][0]


@pytest.mark.asyncio
async def test_emergency_trigger_fires_on_stale_strategy():
    board = make_board()
    triggered = await board.check_emergency_triggers({
        "revenue_flat_days": 0,
        "strategy_unchanged_days": 7,
    })
    assert triggered is True


@pytest.mark.asyncio
async def test_no_emergency_trigger_below_thresholds():
    board = make_board()
    triggered = await board.check_emergency_triggers({
        "revenue_flat_days": 2,
        "strategy_unchanged_days": 5,
    })
    assert triggered is False
    board._redis.publish.assert_not_called()


@pytest.mark.asyncio
async def test_quorum_reached_when_three_votes_cast():
    board = make_board()
    call_count = 0

    async def mock_exists(key):
        nonlocal call_count
        call_count += 1
        # First 3 shareholders have voted
        voted = SHAREHOLDERS[:3]
        return any(sid in key for sid in voted)

    board._redis.exists = mock_exists
    result = await board.quorum_reached()
    assert result is True


def test_board_vote_round_trips_json():
    vote = BoardVote("shareholder-activist", "RESET", "Total failure")
    restored = BoardVote.from_json(vote.to_json())
    assert restored.shareholder_id == vote.shareholder_id
    assert restored.vote == vote.vote
    assert restored.rationale == vote.rationale


@pytest.mark.asyncio
async def test_tally_with_quorum_raises_when_below_minimum():
    """Emergency tally must not silently default to PIVOT on missing votes."""
    board = make_board()
    # Only 3 of 5 votes cast (below QUORUM_MIN_VOTES=4)
    votes = [
        BoardVote("shareholder-activist", "PIVOT", ""),
        BoardVote("shareholder-conservative", "CONTINUE", ""),
        BoardVote("shareholder-diversifier", "RESET", ""),
    ]
    votes_json = {
        f"clawbot:board:votes:2026-05-15:{v.shareholder_id}": v.to_json() for v in votes
    }

    async def mock_get(key):
        return votes_json.get(key)
    board._redis.get = mock_get

    with pytest.raises(QuorumNotReached) as excinfo:
        await board.tally_votes("2026-05-15", require_quorum=True)
    assert excinfo.value.cast == 3
    assert "shareholder-longterm" in excinfo.value.missing


@pytest.mark.asyncio
async def test_tally_with_quorum_succeeds_when_four_votes_cast():
    board = make_board()
    votes = [
        BoardVote("shareholder-activist", "CONTINUE", ""),
        BoardVote("shareholder-conservative", "CONTINUE", ""),
        BoardVote("shareholder-diversifier", "PIVOT", ""),
        BoardVote("shareholder-longterm", "CONTINUE", ""),
    ]
    votes_json = {
        f"clawbot:board:votes:2026-05-15:{v.shareholder_id}": v.to_json() for v in votes
    }

    async def mock_get(key):
        return votes_json.get(key)
    board._redis.get = mock_get

    resolution = await board.tally_votes("2026-05-15", require_quorum=True)
    assert resolution.outcome == "CONTINUE"


def test_quorum_min_votes_is_four():
    """Documented invariant: 1 missing vote tolerated, 2+ requires re-collection."""
    assert QUORUM_MIN_VOTES == 4
