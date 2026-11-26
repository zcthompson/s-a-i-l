"""Add retained RVTools imports and allowlisted equipment inventory."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_add_rvtools_imports"
down_revision: Union[str, None] = "0010_add_intelligence_imports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("rvtools_imports"):
        op.create_table(
            "rvtools_imports",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("customer_id", sa.Integer,
                      sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("file_data", sa.LargeBinary, nullable=False),
            sa.Column("rvtools_version", sa.String(255)),
            sa.Column("collection_at", sa.DateTime),
            sa.Column("vcenter", sa.String(255)),
            sa.Column("vcenter_version", sa.String(255)),
            sa.Column("host_count", sa.Integer, nullable=False),
            sa.Column("vm_count", sa.Integer, nullable=False),
            sa.Column("datastore_count", sa.Integer, nullable=False),
            sa.Column("license_count", sa.Integer, nullable=False),
            sa.Column("created_customer", sa.Boolean, nullable=False),
            sa.Column("datacenters", sa.JSON, nullable=False),
            sa.Column("clusters", sa.JSON, nullable=False),
            sa.Column("datastores", sa.JSON, nullable=False),
            sa.Column("esxi_versions", sa.JSON, nullable=False),
            sa.Column("guest_os_summary", sa.JSON, nullable=False),
            sa.Column("summary", sa.JSON, nullable=False),
            sa.Column("imported_by", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
    if not inspector.has_table("rvtools_hosts"):
        op.create_table(
            "rvtools_hosts",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("import_id", sa.Integer,
                      sa.ForeignKey("rvtools_imports.id", ondelete="CASCADE"), nullable=False),
            sa.Column("host_name", sa.String(255)),
            sa.Column("datacenter", sa.String(255)),
            sa.Column("cluster", sa.String(255)),
            sa.Column("config_status", sa.String(255)),
            sa.Column("maintenance_mode", sa.Boolean),
            sa.Column("cpu_model", sa.String(255)),
            sa.Column("cpu_mhz", sa.Integer),
            sa.Column("sockets", sa.Integer),
            sa.Column("cores_per_socket", sa.Integer),
            sa.Column("cores", sa.Integer),
            sa.Column("memory_mb", sa.Integer),
            sa.Column("nics", sa.Integer),
            sa.Column("hbas", sa.Integer),
            sa.Column("vm_count", sa.Integer),
            sa.Column("vcpu_count", sa.Integer),
            sa.Column("vmotion", sa.Boolean),
            sa.Column("storage_vmotion", sa.Boolean),
            sa.Column("evc_mode", sa.String(255)),
            sa.Column("esxi_version", sa.String(255)),
            sa.Column("vendor", sa.String(255)),
            sa.Column("model", sa.String(255)),
            sa.Column("service_tag", sa.String(255)),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
    if not inspector.has_table("rvtools_vms"):
        op.create_table(
            "rvtools_vms",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("import_id", sa.Integer,
                      sa.ForeignKey("rvtools_imports.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255)),
            sa.Column("power_state", sa.String(255)),
            sa.Column("cpus", sa.Integer),
            sa.Column("memory_mb", sa.Integer),
            sa.Column("disks", sa.Integer),
            sa.Column("disk_capacity_mib", sa.Integer),
            sa.Column("guest_os", sa.String(255)),
            sa.Column("host", sa.String(255)),
            sa.Column("cluster", sa.String(255)),
            sa.Column("datacenter", sa.String(255)),
            sa.Column("datastore", sa.String(255)),
            sa.Column("primary_ip", sa.String(255)),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
    if not inspector.has_table("rvtools_licenses"):
        op.create_table(
            "rvtools_licenses",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("import_id", sa.Integer,
                      sa.ForeignKey("rvtools_imports.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255)),
            sa.Column("cost_unit", sa.String(255)),
            sa.Column("total", sa.Integer),
            sa.Column("used", sa.Integer),
            sa.Column("expiration", sa.String(255)),
            sa.Column("features", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("rvtools_licenses", "rvtools_vms", "rvtools_hosts", "rvtools_imports"):
        if inspector.has_table(table):
            op.drop_table(table)
