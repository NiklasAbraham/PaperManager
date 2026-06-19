# pythonpath = . in pytest.ini handles path setup

import os

# The endpoint tests drive the app through httpx's ASGI transport with
# base_url="http://test", so the request Host header is "test". The app wraps
# itself in TrustedHostMiddleware (default allowed hosts: localhost,127.0.0.1),
# which would reject that Host with "400 Invalid host header". Allow the test
# host here before main/config is imported. setdefault keeps any real
# environment override (e.g. CI) intact.
os.environ.setdefault("TRUSTED_HOSTS", "localhost,127.0.0.1,test,testserver")
