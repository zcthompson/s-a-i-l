"""E5 additive technology facts persist and retain existing update semantics."""

import pytest
from backend.auth import create_access_token
from backend.models.use_case import Customer


def headers():
    return {"Authorization": f"Bearer {create_access_token({'sub': 'admin'})}"}


def test_eol_fields_roundtrip_and_omitted_updates(client, db_session):
    account = Customer(name="Synthetic EOL persistence")
    db_session.add(account)
    db_session.commit()
    url = f"/api/customers/{account.id}/technology/"
    original = client.post(url, headers=headers(), json={"name": "Synthetic", "category": "software"})
    assert original.status_code == 201, original.text
    assert original.json()["end_of_support_date"] is None and original.json()["eol_source"] is None
    item_url = f"/api/technology/{original.json()['id']}/"
    for payload, expected in [
        ({"end_of_support_date": "2027-01-31", "eol_source": "Synthetic vendor notice"},
         ("2027-01-31", "Synthetic vendor notice")),
        ({"name": "Renamed"}, ("2027-01-31", "Synthetic vendor notice")),
        ({"end_of_support_date": None, "eol_source": None}, (None, None)),
    ]:
        response = client.put(item_url, headers=headers(), json=payload)
        assert response.status_code == 200, response.text
        assert (response.json()["end_of_support_date"], response.json()["eol_source"]) == expected
    response = client.post(url, headers=headers(), json={"name": "Dated", "category": "software",
                                  "end_of_support_date": "2027-02-01", "eol_source": "Synthetic"})
    assert response.status_code == 201
    from backend.models.customer_technology import CustomerTechnology
    record = db_session.get(CustomerTechnology, response.json()["id"])
    assert record.to_dict()["end_of_support_date"] == "2027-02-01"
    assert record.to_dict()["eol_source"] == "Synthetic"


@pytest.mark.parametrize("payload", [{"end_of_support_date": "invalid"}, {"eol_source": "x" * 256}])
def test_eol_validation(client, db_session, payload):
    account = Customer(name="Synthetic EOL validation")
    db_session.add(account)
    db_session.commit()
    response = client.post(f"/api/customers/{account.id}/technology/", headers=headers(),
                           json={"name": "Synthetic", "category": "software", **payload})
    assert response.status_code == 422
