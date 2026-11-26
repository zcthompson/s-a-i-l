"""Appearance belongs to the authenticated account, never a supplied user id."""
from backend.models.use_case import User

from tests.backend.test_customer_contacts import headers


def test_account_appearance_isolation_validation_and_reload(client, db_session):
    db_session.add(User(username="appearance_other", approved=1, is_active=1))
    db_session.commit()
    url = "/api/preferences/appearance/"
    assert client.get(url).status_code == 401
    assert client.put(url, json={"theme": "dark", "fontSize": "small"}).status_code == 401
    assert client.get(url, headers=headers()).json() == {"appearance": None}
    appearance = {"theme": "dark", "fontSize": "small"}
    assert client.put(url, headers=headers(), json=appearance).json() == {"appearance": appearance}
    assert client.get(url, headers=headers()).json() == {"appearance": appearance}
    assert client.get(url, headers=headers("appearance_other")).json() == {"appearance": None}
    for invalid in [{**appearance, "user_id": 999}, {**appearance, "theme": "system"}, {**appearance, "fontSize": "tiny"}]:
        assert client.put(url, headers=headers(), json=invalid).status_code == 422
    appearance["fontSize"] = "medium"
    assert client.put(url, headers=headers(), json=appearance).status_code == 200
    assert client.get(url, headers=headers()).json()["appearance"] == appearance
