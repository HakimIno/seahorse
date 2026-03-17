from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Team(BaseModel):
    id: int
    name: str | None = None
    logo: str | None = None
    winner: bool | Any = None


class Goals(BaseModel):
    home: int | None = None
    away: int | None = None


class FixtureStatus(BaseModel):
    long: str | None = None
    short: str | None = None
    elapsed: int | Any = None


class Fixture(BaseModel):
    id: int
    referee: str | None = None
    timezone: str
    date: datetime
    timestamp: int
    status: FixtureStatus


class League(BaseModel):
    id: int
    name: str | None = None
    country: str | None = None
    logo: str | None = None
    flag: str | None = None
    season: int | Any = None
    round: str | None = None


class FullMatchData(BaseModel):
    fixture: Fixture
    league: League
    teams: dict[str, Team]
    goals: Goals
    score: dict[str, Goals]


class PredictionPercent(BaseModel):
    home: str
    draw: str
    away: str


class PredictionTeamDetail(BaseModel, extra="allow"):
    """Extended team info from the predictions endpoint.

    ``extra="allow"`` ensures fields like ``last_5``, ``league``, etc.
    are preserved instead of being silently stripped by Pydantic.
    """

    id: int
    name: str | None = None
    logo: str | None = None
    winner: bool | Any = None


class PredictionTeams(BaseModel, extra="allow"):
    home: PredictionTeamDetail
    away: PredictionTeamDetail


class PredictionData(BaseModel, extra="allow"):
    predictions: dict[str, Any]
    teams: PredictionTeams
    comparison: dict[str, Any]
    h2h: list[Any] = []


class OddsValue(BaseModel):
    value: Any  # e.g., "Home", "Draw", "Away" or "1.5"
    odd: Any    # Decimal odds as string or float


class BookmakerBet(BaseModel):
    id: int | Any = None
    name: str | None = None
    values: list[OddsValue]


class Bookmaker(BaseModel):
    id: int | Any = None
    name: str | None = None
    bets: list[BookmakerBet]


class OddsResponse(BaseModel):
    league: dict[str, Any]
    fixture: dict[str, Any]
    bookmakers: list[Bookmaker]


class APIFootballResponse(BaseModel):
    get: str
    parameters: dict[str, Any]
    errors: list[Any] | dict[str, Any]
    results: int
    paging: dict[str, int]
    response: list[Any]
