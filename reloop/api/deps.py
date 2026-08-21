"""FastAPI 依赖: 数据库会话 + 当前用户(数据隔离键)。

用户识别:
  - 生产(auth_require_token=True): 必须带飞书扫码登录态 X-Auth-Token
  - 开发(auth_require_token=False): 允许 X-Owner-User-Id 直接指定隔离键联调
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
    """解析当前用户(数据隔离键来源)。

    生产(auth_require_token=True):
      必须带有效 X-Auth-Token(飞书扫码登录态), 否则 401;
      X-Owner-User-Id 不再作为鉴权 fallback, 杜绝任填隔离键伪造他人数据。

    开发(auth_require_token=False):
      允许 X-Awner-User-Id 直接指定隔离键(配合 auth_auto_register 便于联调);
      仍优先用 X-Auth-Token(登录态优先)。
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

    # 无登录态: 生产直接拒绝
    if settings.auth_require_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录: 请在设置页扫码登录后访问(缺少 X-Auth-Token)",
        )

    # 开发期 fallback: X-Owner-User-Id
    if not x_owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 X-Owner-User-Id 请求头(开发期)或 X-Auth-Token 登录态",
        )
    user = db.query(User).filter(User.user_id == x_owner_user_id).first()
    if user is None:
        if not settings.auth_auto_register:
            # 开发期若也关闭自动注册: 未注册用户直接拒绝
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
