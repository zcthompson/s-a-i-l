"""Retained RVTools workbooks and the explicitly allowed inventory fields."""

from datetime import UTC, datetime

import sqlalchemy as sa

from backend.models.intelligence_import import _wire
from backend.models.use_case import Base


class RvToolsImport(Base):
    __tablename__ = "rvtools_imports"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    customer_id = sa.Column(
        sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False,
    )
    file_name = sa.Column(sa.String(255), nullable=False)
    file_sha256 = sa.Column(sa.String(64), nullable=False)
    file_data = sa.Column(sa.LargeBinary, nullable=False)
    rvtools_version = sa.Column(sa.String(255))
    collection_at = sa.Column(sa.DateTime)
    vcenter = sa.Column(sa.String(255))
    vcenter_version = sa.Column(sa.String(255))
    host_count = sa.Column(sa.Integer, nullable=False)
    vm_count = sa.Column(sa.Integer, nullable=False)
    datastore_count = sa.Column(sa.Integer, nullable=False)
    license_count = sa.Column(sa.Integer, nullable=False)
    created_customer = sa.Column(sa.Boolean, nullable=False, default=False)
    datacenters = sa.Column(sa.JSON, nullable=False, default=list)
    clusters = sa.Column(sa.JSON, nullable=False, default=list)
    datastores = sa.Column(sa.JSON, nullable=False, default=list)
    esxi_versions = sa.Column(sa.JSON, nullable=False, default=list)
    guest_os_summary = sa.Column(sa.JSON, nullable=False, default=dict)
    summary = sa.Column(sa.JSON, nullable=False, default=dict)
    imported_by = sa.Column(sa.String(100), nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def to_dict(self):
        return {
            "import_id": self.id,
            **{column.name: _wire(getattr(self, column.name)) for column in self.__table__.columns
               if column.name not in {"id", "file_data", "file_sha256"}},
        }


def _inventory_dict(record):
    return {column.name: _wire(getattr(record, column.name)) for column in record.__table__.columns
            if column.name not in {"import_id", "created_at"}}


class RvToolsHost(Base):
    __tablename__ = "rvtools_hosts"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    import_id = sa.Column(
        sa.Integer, sa.ForeignKey("rvtools_imports.id", ondelete="CASCADE"), nullable=False,
    )
    host_name = sa.Column(sa.String(255))
    datacenter = sa.Column(sa.String(255))
    cluster = sa.Column(sa.String(255))
    config_status = sa.Column(sa.String(255))
    maintenance_mode = sa.Column(sa.Boolean)
    cpu_model = sa.Column(sa.String(255))
    cpu_mhz = sa.Column(sa.Integer)
    sockets = sa.Column(sa.Integer)
    cores_per_socket = sa.Column(sa.Integer)
    cores = sa.Column(sa.Integer)
    memory_mb = sa.Column(sa.Integer)
    nics = sa.Column(sa.Integer)
    hbas = sa.Column(sa.Integer)
    vm_count = sa.Column(sa.Integer)
    vcpu_count = sa.Column(sa.Integer)
    vmotion = sa.Column(sa.Boolean)
    storage_vmotion = sa.Column(sa.Boolean)
    evc_mode = sa.Column(sa.String(255))
    esxi_version = sa.Column(sa.String(255))
    vendor = sa.Column(sa.String(255))
    model = sa.Column(sa.String(255))
    service_tag = sa.Column(sa.String(255))
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def to_dict(self):
        return _inventory_dict(self)


class RvToolsVM(Base):
    __tablename__ = "rvtools_vms"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    import_id = sa.Column(
        sa.Integer, sa.ForeignKey("rvtools_imports.id", ondelete="CASCADE"), nullable=False,
    )
    name = sa.Column(sa.String(255))
    power_state = sa.Column(sa.String(255))
    cpus = sa.Column(sa.Integer)
    memory_mb = sa.Column(sa.Integer)
    disks = sa.Column(sa.Integer)
    disk_capacity_mib = sa.Column(sa.Integer)
    guest_os = sa.Column(sa.String(255))
    host = sa.Column(sa.String(255))
    cluster = sa.Column(sa.String(255))
    datacenter = sa.Column(sa.String(255))
    datastore = sa.Column(sa.String(255))
    primary_ip = sa.Column(sa.String(255))
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def to_dict(self):
        return _inventory_dict(self)


class RvToolsLicense(Base):
    __tablename__ = "rvtools_licenses"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    import_id = sa.Column(
        sa.Integer, sa.ForeignKey("rvtools_imports.id", ondelete="CASCADE"), nullable=False,
    )
    name = sa.Column(sa.String(255))
    cost_unit = sa.Column(sa.String(255))
    total = sa.Column(sa.Integer)
    used = sa.Column(sa.Integer)
    expiration = sa.Column(sa.String(255))
    features = sa.Column(sa.Text)
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def to_dict(self):
        return _inventory_dict(self)
