import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import settings

_PROBE_PATH_RE = re.compile(
    r"""(?ix)
    \.(?:php|phtml|phar|sh|sql|bak|old|orig|swp|zip|tar|gz)(?:\?|$|/)|
    /\.(?:env|git|svn|hg|bzr|htpasswd|htaccess)(?:/|$)|
    (?:^|/)\.env(?:\.|\?|$|/)|
    [^/]+\.env(?:\?|$|/)|
    (?:^|/)(?:wp-admin|wp-includes|wp-content|wp-login\.php|xmlrpc\.php)(?:/|$)|
    (?:^|/)(?:phpmyadmin|pma|adminer|vendor/phpunit)(?:/|$)|
    (?:^|/)cgi-bin(?:/|$)|
    (?:^|/)(?:wlwmanifest\.xml|readme\.html|license\.txt)(?:/|$)
    """
)


def suspicious_request_path(path: str) -> bool:
    return bool(_PROBE_PATH_RE.search(path))



class ProbeBlockMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.block_probe_paths:
            return await call_next(request)
        p = request.url.path
        if p.startswith('/static/'):
            return await call_next(request)
        if suspicious_request_path(p):
            return Response(status_code=404, content=b'Not Found', media_type='text/plain')
        return await call_next(request)
