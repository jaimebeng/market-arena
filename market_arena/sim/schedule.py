"""Scheduled events and trading sessions.

- Shock: a scheduled fair-value jump with a headline (a tariff announcement, earnings after the close).
- SessionParams: a 23-hour trading day. Epochs alternate between the regular session and an overnight
  session. Overnight, every scripted participant is active only `night_activity` of the time (a
  thinned order flow), while news keeps arriving. With `night_trading` off the exchange is closed
  overnight, as US equities were before 23x5: resting orders expire at the close, nothing trades,
  and the book is re-seeded at the open around the crowd's (lagged) view of the value.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Shock(BaseModel):
    at_step: int
    asset: str = "A"
    bps: float = -300.0
    headline: str = ""


class SessionParams(BaseModel):
    pattern: list[str] = Field(default_factory=lambda: ["day", "night"])  # cycled over epochs
    night_trading: bool = True  # False: the exchange is closed overnight
    night_activity: float = 0.1  # share of the daytime order flow that is active overnight

    def kind(self, epoch: int) -> str:
        return self.pattern[epoch % len(self.pattern)]
