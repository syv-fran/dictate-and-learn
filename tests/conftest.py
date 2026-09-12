import pytest

from backend.app import app as flask_app


@pytest.fixture()
def app():
    flask_app.config.update(
        {
            "TESTING": True, # this causes exceptions to propagate
        }
    )
    yield flask_app

@pytest.fixture()
def client(app):
    return app.test_client()

