import sqlite3
import shutil
import tempfile
import pytest
from flask import g

import app

@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    shutil.copy("databases.db", db_path)

    def get_test_db():
        if "db" not in g:
            g.db = sqlite3.connect(db_path)
            g.db.row_factory = sqlite3.Row
        return g.db

    app.get_db = get_test_db
    app.config["TESTING"] = True

    with app.app.test_client() as client:
        with app.app.app_context():
            yield client
        g.pop("db", None)

def test_register_get(client):
    resp = client.get('/register')
    assert resp.status_code == 200

def test_index_payment_post_redirect(client):
    data = {
        'movement_id': '1',
        'draft_id': '0',
        'amount': '5',
        'payment_method[]': 'cash',
        'payment_amount[]': '5'
    }
    resp = client.post('/index_payment', data=data)
    assert resp.status_code in (301, 302)

def test_search_inventory_movements_returns_json(client):
    resp = client.get('/search_inventory_movements?q=test')
    assert resp.status_code == 200
    assert resp.is_json
    assert isinstance(resp.get_json(), list)
