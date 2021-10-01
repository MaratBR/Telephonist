import unittest

from starlette.testclient import TestClient

from server import app


class TestTelephonistWS(unittest.TestCase):
    def test_some(self):
        client = TestClient(app)
        with client.websocket_connect('/ws') as ws:
            pass
