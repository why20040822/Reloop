"""FastAPI 依赖: 数据库会话 + 当前用户(数据隔离键)。

用户识别:
  - 开发期: 请求头 X-Owner-User-Id 传入用户唯一标识
  - 后期前端接入后: 替换为登录态/SSO 解析(此处是唯一需要改的地方)
"""

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from reloop.config import settings
from reloop.db.engine import get_db
from reloop.db.models import User

logger = logging.getLogger(__name__)


def get_current_user(
    db: Session = Depends(get_db),
    x_owner_user_id: Optional[str] = Header(default=None, alias="X-Owner-User-Id"),
) -> User:
    """解析当前用户(数据隔离键来源), 未注册则自动注册(便于开发联调)。"""
    if not x_owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 X-Owner-User-Id 请求头(用户唯一标识)",
        )
    user = db.query(User).filter(User.user_id == x_owner_user_id).first()
    if user is None:
        if not settings.auth_auto_register:
            # 生产: 未注册用户直接拒绝, 不再任填任进
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户未注册(auth_auto_register=False)",
            )
        user = User(user_id=x_owner_user_id)
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("[auth] auto-registered user=%s", x_owner_user_id)
    return user


def owner_user_id(user: User = Depends(get_current_user)) -> str:
    """便捷依赖: 直接返回隔离键。"""
    return user.user_id
