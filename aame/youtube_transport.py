"""Explicitly authorized HTTPS transport for YouTube request contracts."""

from dataclasses import dataclass, field
from http.client import HTTPException
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


MAX_RESPONSE_BYTES = 1024 * 1024
_ALLOWED = {
    "/upload/youtube/v3/videos": {"POST", "PUT"},
    "/youtube/v3/videos": {"GET"},
}


class TransportError(RuntimeError):
    pass


class DispatchDenied(TransportError):
    """Authorization or token validation blocked the request before I/O."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict = field(repr=False)
    payload: object = field(repr=False)


class YouTubeTransport:
    """Send one authorized request. Caller owns retries, budgets and OAuth."""

    def __init__(self, *, access_token, authorize, timeout=30, opener=None):
        if type(timeout) is not int or not 1 <= timeout <= 60:
            raise ValueError("invalid HTTPS timeout")
        self._access_token = access_token
        self._authorize = authorize
        self._timeout = timeout
        self._opener = opener or build_opener(ProxyHandler({}), _NoRedirect()).open

    def send(self, request):
        if any(ord(char) < 33 or ord(char) >= 127 for char in request.url):
            raise TransportError("unapproved YouTube endpoint")
        url = urlsplit(request.url)
        if (
            url.scheme != "https"
            or url.netloc != "www.googleapis.com"
            or request.method not in _ALLOWED.get(url.path, ())
            or url.fragment
        ):
            raise TransportError("unapproved YouTube endpoint")
        if self._authorize(request) is not True:
            raise DispatchDenied("YouTube dispatch authorization denied")
        token = self._access_token()
        if not isinstance(token, str) or not token or any(
            ord(char) < 33 or ord(char) >= 127 for char in token
        ):
            raise DispatchDenied("missing or invalid OAuth token")
        headers = {
            key: value for key, value in request.headers.items()
            if key.lower() not in ("authorization", "host", "proxy-authorization")
        }
        headers["Authorization"] = "Bearer " + token
        wire = Request(
            request.url, data=request.body if request.method != "GET" else None,
            headers=headers, method=request.method,
        )
        try:
            try:
                response = self._opener(wire, timeout=self._timeout)
            except HTTPError as error:
                response = error
            with response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise TransportError("YouTube response exceeds byte limit")
                headers = {}
                for key, value in response.headers.items():
                    key = key.lower()
                    if key in ("range", "location"):
                        if key in headers:
                            raise TransportError("ambiguous YouTube response header")
                        headers[key] = value
                if raw:
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        payload = None
                else:
                    payload = None
                return Response(response.code, headers, payload)
        except (OSError, URLError, HTTPException):
            raise TransportError("YouTube request outcome unknown") from None
