"""Requests must not exhaust cached engine pools or retain failed writes."""
import os

from backend.dependencies import get_db
from backend.test_database import guarded_test_url
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine.create import create_engine
from sqlalchemy.orm import Session, sessionmaker


def test_request_sessions_release_small_pool_after_success_and_failure(tmp_path, monkeypatch):
    url = (guarded_test_url(os.environ['TEST_DATABASE_URL'], reset=True)
           if os.environ.get('TEST_DATABASE_URL') else f'sqlite:///{tmp_path / "pool.db"}')
    engine = create_engine(url, pool_size=1,
                           max_overflow=0, pool_timeout=0.1)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE session_pool_probe (value INTEGER)'))
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr('backend.dependencies.get_session', factory)
    app = FastAPI()

    @app.get('/read')
    def read(db: Session = Depends(get_db)):
        return {'value': db.scalar(text('SELECT 1'))}

    @app.post('/fail')
    def fail(db: Session = Depends(get_db)):
        db.execute(text('INSERT INTO session_pool_probe(value) VALUES (1)'))
        raise HTTPException(status_code=409, detail='expected test failure')

    try:
        with TestClient(app) as client:
            for _ in range(30):
                assert client.get('/read').json() == {'value': 1}
                assert client.post('/fail').status_code == 409
                assert engine.pool.checkedout() == 0
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT COUNT(*) FROM session_pool_probe')) == 0
    finally:
        with engine.begin() as connection:
            connection.execute(text('DROP TABLE session_pool_probe'))
        engine.dispose()
