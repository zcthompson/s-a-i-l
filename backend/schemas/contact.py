"""Contract-derived contact request and response schemas."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class BuyingRoleInput(BaseModel):
    role: str
    source: str | None = Field(None, max_length=255)
    observation_date: date | None = None
    verification_state: str = "verified"


class ContactFields(BaseModel):
    title: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    department: str | None = Field(None, max_length=100)
    persona: str | None = Field(None, max_length=50)
    source: str | None = Field(None, max_length=255)
    observation_date: date | None = None


class ContactCreate(ContactFields):
    display_name: str = Field(..., max_length=255)
    verification_state: str = "verified"
    buying_roles: list[BuyingRoleInput] = Field(default_factory=list)
    related_note_ids: list[int] = Field(default_factory=list)
    related_use_case_ids: list[int] = Field(default_factory=list)
    related_technology_ids: list[int] = Field(default_factory=list)


class ContactUpdate(ContactFields):
    display_name: str | None = Field(None, max_length=255)
    verification_state: str | None = None
    buying_roles: list[BuyingRoleInput] | None = None
    related_note_ids: list[int] | None = None
    related_use_case_ids: list[int] | None = None
    related_technology_ids: list[int] | None = None
    archived: bool | None = None


class BuyingRole(BuyingRoleInput):
    role_label: str


class Contact(ContactFields):
    id: int
    customer_id: int
    display_name: str
    persona_label: str | None
    verification_state: str
    buying_roles: list[BuyingRole]
    related_note_ids: list[int]
    related_use_case_ids: list[int]
    related_technology_ids: list[int]
    note_count: int
    archived: bool
    archived_at: datetime | None
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime


class ContactCoverage(BaseModel):
    customer_id: int
    calc_version: str
    source: str
    contacts_recorded: int
    archived_count: int
    roles: dict[str, int]
    economic_buyer_recorded: bool
    champion_recorded: bool
    personas: dict[str, int]
    persona_unknown: int
    gaps: list[str]
    last_contacted: str | None
    last_contacted_basis: str
