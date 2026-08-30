"""公司共享池快照表(v2.2): 持久化 + TTL 刷新 + 空拉保留旧快照。"""

import os

os.environ.setdefault("BRAINX_AUTH_REQUIRE_TOKEN", "false")
os.environ.setdefault("BRAINX_AUTH_SESSION_SECRET", "test-company-pool")

from reloop.db.engine import SessionLocal, init_db  # noqa: E402
from reloop.db.models import CompanyPoolSnapshot  # noqa: E402
from reloop.modules.sync import company_pool  # noqa: E402

_FAKE_POOL = [
    {"source_id": "PT001", "notes": "备注A", "seek_status": "已离职找工作", "company": "甲公司"},
    {"source_id": "PT002", "notes": "备注B", "seek_status": "在职看机会", "company": "乙公司"},
]


class _FakeClient:
    def __init__(self, items=None):
        self.items = _FAKE_POOL if items is None else items
        self.calls = 0

    def fetch_talents(self, **kwargs):
        self.calls += 1
        return self.items


def _reset():
    init_db()
    db = SessionLocal()
    db.query(CompanyPoolSnapshot).delete()
    db.commit()
    db.close()
    company_pool._mem_view = {"fetched_at": None, "by_sid": {}, "total": 0}


def test_snapshot_persisted_and_cached():
    """首拉写表; TTL 内不再重拉; by_sid 可查。"""
    _reset()
    client = _FakeClient()
    snap = company_pool.get_shared_snapshot(client)
    assert snap["total"] == 2
    assert snap["by_sid"]["PT001"]["notes"] == "备注A"
    assert client.calls == 1

    db = SessionLocal()
    assert db.query(CompanyPoolSnapshot).count() == 2
    db.close()

    # TTL 内第二次调用: 不重拉(清掉内存视图验证读表路径)
    company_pool._mem_view = {"fetched_at": None, "by_sid": {}, "total": 0}
    snap2 = company_pool.get_shared_snapshot(client)
    assert snap2["total"] == 2
    assert client.calls == 1


def test_force_refresh_and_empty_fetch_guard():
    """force=True 强制重拉; 拉到空保留旧快照。"""
    _reset()
    client = _FakeClient()
    company_pool.get_shared_snapshot(client)
    assert client.calls == 1

    company_pool.get_shared_snapshot(client, force=True)
    assert client.calls == 2

    # 空拉: 旧快照保留(整表不被清空)
    empty_client = _FakeClient(items=[])
    snap = company_pool.get_shared_snapshot(empty_client, force=True)
    db = SessionLocal()
    assert db.query(CompanyPoolSnapshot).count() == 2
    db.close()
    assert snap["total"] == 2


def test_supplement_found_and_not_found():
    """撞库: 命中返回 supplement+diff; 未命中/缺 sid 返回原因。"""
    _reset()
    company_pool.get_shared_snapshot(_FakeClient())

    class _T:
        source_id = "PT001"
        notes = "旧备注"
        seek_status = None
        contact_status = None
        company = "甲公司"
        position = None
        current_salary = expected_salary = None

    res = company_pool.get_company_supplement(_T())
    assert res["found"] is True
    assert res["supplement"]["notes"] == "备注A"
    fields = {d["field"] for d in res["diff"]}
    assert "notes" in fields and "seek_status" in fields

    class _U:
        source_id = "PT999"
        notes = seek_status = contact_status = company = position = None
        current_salary = expected_salary = None

    res2 = company_pool.get_company_supplement(_U())
    assert res2["found"] is False
    assert "未找到" in res2["message"]
