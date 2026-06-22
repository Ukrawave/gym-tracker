"""Strava data source (Phase 0).

DIY OAuth (no `stravalib` dependency): refresh the access token, then page the
athlete's activities. `requests` is lazy-imported inside the network methods so
this module — and its pure `normalize_activity` — import and unit-test with no
`requests` installed and no network access. The orchestrator (Task 7) runs the
real fetch.
"""
from __future__ import annotations

from typing import Any, Optional

from app.sources.base import coerce_float, coerce_int, store_raw

TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"


class StravaSource:
    """Fetch (network) + normalize (pure) for Strava API v3.

    Credentials may be None when only `normalize_activity` is used (tests).
    """

    source = "strava"

    def __init__(
        self,
        client_id: Optional[str],
        client_secret: Optional[str],
        refresh_token: Optional[str],
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._access_token: Optional[str] = None

    # ------------------------------------------------------------------
    # Network — lazy-imported, never exercised by the offline test suite.
    # ------------------------------------------------------------------
    def refresh_access_token(self) -> str:
        """Exchange the refresh token for a short-lived access token. NETWORK."""
        import requests  # lazy: keep import offline-safe

        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._access_token = payload["access_token"]
        # Strava rotates the refresh token; keep the newest so the next run works.
        if payload.get("refresh_token"):
            self.refresh_token = payload["refresh_token"]
        return self._access_token

    def fetch_activities(self, after_epoch: int, per_page: int = 100) -> list[dict]:
        """GET /athlete/activities?after=<epoch>, paged. NETWORK.

        Returns the concatenated raw activity dicts (newest sources paginate
        until a short page is returned).
        """
        import requests  # lazy

        if self._access_token is None:
            self.refresh_access_token()

        headers = {"Authorization": f"Bearer {self._access_token}"}
        out: list[dict] = []
        page = 1
        while True:
            resp = requests.get(
                ACTIVITIES_URL,
                headers=headers,
                params={"after": after_epoch, "per_page": per_page, "page": page},
                timeout=30,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return out

    # ------------------------------------------------------------------
    # Normalizer — PURE, fixture-tested, no network.
    # ------------------------------------------------------------------
    def normalize_activity(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map one Strava activity dict to an `activities` row."""
        row = {
            "id": f"strava:{raw['id']}",
            "source": self.source,
            # VALIDATE: sport_type is the newer/more specific field; type is the
            # legacy one. Prefer type for parity with Garmin's coarse type.
            "type": raw.get("type") or raw.get("sport_type"),
            "start_time": raw.get("start_date"),
            # elapsed_time is wall-clock; moving_time excludes pauses. Use
            # elapsed_time as duration_s for parity with Garmin's `duration`.
            "duration_s": coerce_int(raw.get("elapsed_time")),
            "distance_m": coerce_float(raw.get("distance")),
            "avg_hr": coerce_int(raw.get("average_heartrate")),
            "elevation_m": coerce_float(raw.get("total_elevation_gain")),
            # VALIDATE: calories present only on detailed fetch for some
            # activities; may be absent on the list endpoint.
            "calories": coerce_int(raw.get("calories")),
        }
        return store_raw(row, raw)
