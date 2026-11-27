"""
Where the document styles (and their rules) are kept.

- SupabaseStore: a Supabase (Postgres) database, editable from the "Manage rules" page. Every save or
  delete keeps the previous version in style_history (a database trigger, see supabase/migrations/).
- YamlStore: the rules/*.yaml files in the repo. Read-only. Used when Supabase isn't configured or
  can't be reached, and as the example rules for an empty database.
"""

import os
from functools import lru_cache

import httpx

from checker.styles import RULES_DIR, Style, load_styles


class StoreError(Exception):
    pass


class YamlStore:
    editable = False
    label = "rules/*.yaml files"

    def __init__(self, rules_dir=RULES_DIR):
        self.rules_dir = rules_dir

    def list_styles(self) -> dict[str, Style]:
        return load_styles(self.rules_dir)


class SupabaseStore:
    editable = True
    label = "Supabase database"

    def __init__(self, url: str, key: str, transport: httpx.BaseTransport | None = None):
        headers = {"apikey": key, "Content-Type": "application/json"}
        if key.startswith("eyJ"):
            # Legacy JWT keys (service_role) also go in Authorization; new sb_secret_ keys must not
            headers["Authorization"] = f"Bearer {key}"
        self._http = httpx.Client(
            base_url=f"{url.rstrip('/')}/rest/v1", headers=headers, timeout=10, transport=transport
        )

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self._http.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise StoreError(f"Supabase error {e.response.status_code}: {e.response.text[:200]}") from e
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            raise StoreError(f"Can't reach Supabase: {e}") from e
        return response

    def _rows(self, path: str, required: str, **params) -> list[dict]:
        response = self._request("GET", path, params={"select": "*", **params})
        try:
            rows = response.json()
        except ValueError as e:  # e.g. an HTML page from a proxy or a wrong SUPABASE_URL
            raise StoreError("Supabase gave an unreadable answer. Check SUPABASE_URL.") from e
        if not isinstance(rows, list) or not all(isinstance(row, dict) and row.get(required) for row in rows):
            raise StoreError("Supabase gave an unexpected answer. Check SUPABASE_URL.")
        return rows

    def list_styles(self) -> dict[str, Style]:
        return {row["id"]: Style.from_dict(row) for row in self._rows("/styles", "id", order="id")}

    def save_style(self, style: Style, editor: str) -> None:
        """
        Creates the style, or replaces it if the ID already exists (the old version goes to history).
        """
        self._save({**style.to_dict(), "updated_by": editor})

    def save_styles(self, styles: list[Style], editor: str) -> None:
        """
        Saves all the styles, or none of them if one can't be saved.
        """
        self._save([{**style.to_dict(), "updated_by": editor} for style in styles])

    def _save(self, body: dict | list[dict]) -> None:
        self._request("POST", "/styles", json=body, headers={"Prefer": "resolution=merge-duplicates,return=minimal"})

    def delete_style(self, style_id: str) -> None:
        self._request("DELETE", "/styles", params={"id": f"eq.{style_id}"})

    def history(self, limit: int = 50) -> list[dict]:
        """
        Previous versions, newest first. Each row is the style as it was *before* that change.
        """
        return self._rows("/style_history", "style_id", order="archived_at.desc", limit=limit)

    def restore(self, history_row: dict, editor: str) -> None:
        self.save_style(Style.from_dict({**history_row, "id": history_row["style_id"]}), editor)


@lru_cache(maxsize=1)
def _supabase(url: str, key: str) -> SupabaseStore:
    return SupabaseStore(url, key)  # one connection pool, shared by all users


def get_store() -> SupabaseStore | YamlStore:
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if url and key:
        return _supabase(url, key)
    return YamlStore()
