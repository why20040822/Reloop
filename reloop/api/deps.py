"""FastAPI 依赖: 数据库会话 + 当前用户(数据隔离键)。

用户识别:
  - 生产(auth_require_token=True): 必须带飞书扫码登录态 X-Auth-Token
  - 开发(auth_require_token=False): 允许 X-Owner-User-Id 直接指定隔离键联调
"""

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reloop.config import settings
from reloop.db.engine import get_db
from reloop.db.models import User
from reloop.modules.auth.feishu import verify_session_token

logger = logging.getLogger(__name__)


def _create_user_or_get_concurrent_winner(db: Session, user_id: str, display_name: str | None = None) -> User:
    user = User(user_id=user_id, display_name=display_name)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.query(User).filter(User.user_id == user_id).first()
        if winner is None:
            raise
        return winner
    db.refresh(user)
    return user


def get_current_user(
    db: Session = Depends(get_db),
    x_owner_user_id: Optional[str] = Header(default=None, alias="X-Owner-User-Id"),
    x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token"),
) -> User:
    """解析当前用户(数据隔离键来源)。

    登录态(X-Auth-Token)优先; 未登录时:
      - auth_require_token=False 且带 X-Owner-User-Id -> 开发期联调隔离键
      - auth_allow_guest=True  -> 返回访客用户(共享池)
      - 否则 401
    """
    # 1. 登录态优先
    if x_auth_token:
        user_id = verify_session_token(x_auth_token)
        if user_id:
            user = db.query(User).filter(User.user_id == user_id).first()
            if user is not None:
                return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录态无效或已过期, 请重新扫码登录",
        )

    # 2. 开发期 fallback: X-Owner-User-Id(仅 auth_require_token=False;
    #    须先于访客分支, 否则默认开访客时该隔离键恒失效)
    if x_owner_user_id and not settings.auth_require_token:
        user = db.query(User).filter(User.user_id == x_owner_user_id).first()
        if user is None:
            if not settings.auth_auto_register:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="用户未注册(auth_auto_register=False)",
                )
            user = _create_user_or_get_concurrent_winner(db, x_owner_user_id)
            logger.info("[auth] auto-registered user=%s", x_owner_user_id)
        return user

    # 3. 无登录态: 看是否允许访客
    if settings.auth_allow_guest:
        user = db.query(User).filter(User.user_id == settings.guest_owner_id).first()
        if user is None:
            user = _create_user_or_get_concurrent_winner(db, settings.guest_owner_id, "访客")
        return user

    # 4. 都不放行 -> 401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录: 请扫码登录后访问(缺少 X-Auth-Token)",
    )


def get_optional_user(
    db: Session = Depends(get_db),
    x_owner_user_id: Optional[str] = Header(default=None, alias="X-Owner-User-Id"),
    x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token"),
) -> Optional[User]:
    """可选用户: 有登录态返回用户实体, 否则 None(不抛异常)。"""
    if x_auth_token:
        user_id = verify_session_token(x_auth_token)
        if user_id:
            return db.query(User).filter(User.user_id == user_id).first()
    if x_owner_user_id:
        return db.query(User).filter(User.user_id == x_owner_user_id).first()
    return None


def owner_user_id(user: User = Depends(get_current_user)) -> str:
    """便捷依赖: 直接返回隔离键。"""
    return user.user_id


def require_authenticated_non_guest_user(
    db: Session = Depends(get_db),
    x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token"),
) -> User:
    """Require an existing signed-in user without guest or development fallbacks.

    Parse previews may submit sensitive raw JD text. This dependency intentionally
    performs no registration or guest provisioning and ignores X-Owner-User-Id.
    """
    if not x_auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要有效登录态",
        )
    user_id = verify_session_token(x_auth_token)
    if not user_id or user_id == settings.guest_owner_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录态无效或已过期, 请重新扫码登录",
        )
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None or user.user_id == settings.guest_owner_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录态无效或已过期, 请重新扫码登录",
        )
    return user
