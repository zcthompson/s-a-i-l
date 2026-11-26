"""Pydantic contracts for the per-customer sales-team correction surface."""


from pydantic import BaseModel, Field


class SalesTeamPrimaryRep(BaseModel):
    user_id: int | None = None
    name: str | None = None
    sales_role: str | None = None


class SalesTeamUser(BaseModel):
    user_id: int
    name: str
    auto_linked: bool = False
    link_reason: str | None = None


class SalesTeamResponse(BaseModel):
    customer_id: int
    primary_rep: SalesTeamPrimaryRep | None = None
    manager: SalesTeamUser | None = None
    inside_sales: list[SalesTeamUser] = Field(default_factory=list)
    sales_ops: list[SalesTeamUser] = Field(default_factory=list)


class SalesTeamUpdate(BaseModel):
    primary_rep_user_id: int | None = None
    manager_user_id: int | None = None
    inside_sales_user_ids: list[int] = Field(default_factory=list)
    sales_ops_user_ids: list[int] = Field(default_factory=list)
