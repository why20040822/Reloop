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
from reloop.modules.auth.feishu import verify_session_token

logger = logging.getLogger(__name__)


def get_current_user(
    db: Session = Depends(get_db),
    x_owner_user_id: Optional[str] = Header(default=None, alias="X-Owner-User-Id"),
    x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token"),
) -> User:
    """解析当前用户(数据隔离键来源), 未注册则自动注册(便于开发联调)。

    优先级:
      1. X-Auth-Token(飞书扫码登录签发的会话 token) -> 解析出 user_id
      2. X-Owner-User-Id(开发期/直连调试用的显式隔离键)
    """
    if x_auth_token:
        user_id = verify_session_token(x_auth_token)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录态无效或已过期, 请重新扫码登录",
            )
        user = db.query(User).filter(User.user_id == user_id).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录用户不存在",
            )
        return user

    if not x_owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 X-Owner-User-Id 请求头(或 X-Auth-Token 登录态)",
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
