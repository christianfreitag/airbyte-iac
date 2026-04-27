import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class AirbyteClient:
    def __init__(
        self,
        base_url: str,
        username: str = None,
        password: str = None,
        token: str = None,
        client_id: str = None,
        client_secret: str = None,
        workspace_id: str = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._static_token = token
        self._client_id = client_id
        self._client_secret = client_secret
        self._basic_auth = HTTPBasicAuth(username, password) if username and password else None
        self._access_token = None
        self._workspace_id = None
        self._forced_workspace_id = workspace_id
        self._session = _make_session()

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        resp = self._session.post(
            f"{self.base_url}/api/v1/applications/token",
            json={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=120,
        )
        if not resp.ok:
            raise RuntimeError(f"Token error {resp.status_code}: {resp.text}")
        data = resp.json()
        self._access_token = data.get("access_token") or data.get("accessToken")
        return self._access_token

    def _headers(self) -> dict:
        if self._client_id and self._client_secret:
            token = self._get_access_token()
            return {"Authorization": f"Bearer {token}"}
        if self._static_token:
            return {
                "Authorization": f"Bearer {self._static_token}",
                "X-Airbyte-Auth": f"Bearer {self._static_token}",
            }
        return {}

    def _post(self, endpoint: str, data: dict) -> dict:
        url = f"{self.base_url}/api/v1/{endpoint}"
        resp = self._session.post(
            url, json=data, auth=self._basic_auth, headers=self._headers(), timeout=120
        )
        resp.raise_for_status()
        return resp.json()

    @property
    def workspace_id(self) -> str:
        if not self._workspace_id:
            self._workspace_id = self._forced_workspace_id or \
                self._post("workspaces/list", {})["workspaces"][0]["workspaceId"]
        return self._workspace_id

    def list_workspaces(self) -> list:
        return self._post("workspaces/list", {})["workspaces"]

    # --- Tags ---

    def list_tags(self) -> list:
        resp = self._post("tags/list", {"workspaceId": self.workspace_id})
        return resp if isinstance(resp, list) else resp.get("tags", [])

    def create_tag(self, name: str) -> dict:
        resp = self._post("tags/create", {"workspaceId": self.workspace_id, "name": name})
        return resp if isinstance(resp, dict) else {"tagId": resp, "name": name}

    # --- Sources ---

    def list_sources(self) -> list:
        return self._post("sources/list", {"workspaceId": self.workspace_id})["sources"]

    def get_source(self, source_id: str) -> dict:
        return self._post("sources/get", {"sourceId": source_id})

    def create_source(self, config: dict) -> dict:
        config["workspaceId"] = self.workspace_id
        return self._post("sources/create", config)

    def update_source(self, source_id: str, config: dict) -> dict:
        config["sourceId"] = source_id
        return self._post("sources/update", config)

    def list_source_definitions(self) -> list:
        return self._post("source_definitions/list_latest", {})["sourceDefinitions"]

    # --- Destinations ---

    def list_destinations(self) -> list:
        return self._post("destinations/list", {"workspaceId": self.workspace_id})["destinations"]

    def get_destination(self, destination_id: str) -> dict:
        return self._post("destinations/get", {"destinationId": destination_id})

    def create_destination(self, config: dict) -> dict:
        config["workspaceId"] = self.workspace_id
        return self._post("destinations/create", config)

    def update_destination(self, destination_id: str, config: dict) -> dict:
        config["destinationId"] = destination_id
        return self._post("destinations/update", config)

    def list_destination_definitions(self) -> list:
        return self._post("destination_definitions/list_latest", {})["destinationDefinitions"]

    # --- Connections ---

    def list_connections(self) -> list:
        return self._post("connections/list", {"workspaceId": self.workspace_id})["connections"]

    def get_connection(self, connection_id: str) -> dict:
        return self._post("connections/get", {"connectionId": connection_id})

    def create_connection(self, config: dict) -> dict:
        return self._post("connections/create", config)

    def update_connection(self, connection_id: str, config: dict) -> dict:
        config["connectionId"] = connection_id
        return self._post("connections/update", config)

    # --- Schema ---

    def discover_schema(self, source_id: str) -> dict:
        return self._post("sources/discover_schema", {"sourceId": source_id})
