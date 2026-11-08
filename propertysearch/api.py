"""Thin client for myhome's runner API (claim / complete / fail)."""
from __future__ import annotations

import httpx

TIMEOUT_S = 30


class MyHomeError(Exception):
    pass


class MyHome:
    def __init__(self, base_url: str, token: str, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=TIMEOUT_S, transport=transport,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    def _post(self, path: str, body: dict | None = None) -> httpx.Response:
        try:
            resp = self._client.post(path, json=body)
        except httpx.HTTPError as e:
            raise MyHomeError(f"myhome unreachable: {e}") from e
        if resp.status_code >= 300:
            raise MyHomeError(f"myhome {path} returned {resp.status_code}: {resp.text[:300]}")
        return resp

    def me(self) -> dict:
        try:
            resp = self._client.get("/api/auth/me")
        except httpx.HTTPError as e:
            raise MyHomeError(f"myhome unreachable: {e}") from e
        if resp.status_code >= 300:
            raise MyHomeError(f"myhome /api/auth/me returned {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def claim(self) -> dict | None:
        resp = self._post("/api/property-search/runner/claim")
        return None if resp.status_code == 204 else resp.json()

    def complete(self, run_id: str, payload: dict) -> dict:
        return self._post(f"/api/property-search/runner/runs/{run_id}/complete", payload).json()

    def fail(self, run_id: str, reason: str, message: str, usage: dict | None = None) -> None:
        self._post(f"/api/property-search/runner/runs/{run_id}/fail",
                   {"reason": reason, "message": message[:1000], "usage": usage})
