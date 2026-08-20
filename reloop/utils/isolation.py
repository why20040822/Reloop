"""数据隔离工具: 所有业务查询必须按 owner_user_id 过滤。"""

from sqlalchemy.orm import Session


def scoped_query(db: Session, model, owner_user_id: str):
    """按隔离键过滤的通用查询入口: scoped_query(db, Model, owner)。"""
    return db.query(model).filter(model.owner_user_id == owner_user_id)


def assert_owner(model, row, owner_user_id: str) -> None:
    """校验行属于该 owner, 否则 403(防越权访问他人人才库)。"""
    row_owner = getattr(row, "owner_user_id", None)
    if row_owner != owner_user_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="无权访问该资源(数据隔离)")
