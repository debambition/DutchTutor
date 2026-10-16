import pytest

from app import auth
from app.main import app


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: run with sign-in enforced")


@pytest.fixture(autouse=True)
def bypass_auth(request):
    """API tests focus on behaviour, not sign-in, unless marked real_auth."""
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    app.dependency_overrides[auth.require_user] = lambda user_id: user_id
    app.dependency_overrides[auth.require_signed_in] = lambda: "tester"
    yield
    app.dependency_overrides.clear()
