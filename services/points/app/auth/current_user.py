"""Who is calling, from the access token alone: Points never asks Checkins.

The token is signed by Checkins with AUTH_TOKEN_SECRET, which Points also has,
so a valid signature and an unexpired "exp" are enough. Accepted cost: after a
logout the token keeps working here until it expires (Checkins sees the logout
at once, because it also checks the session row).
"""

from typing import Optional

from fastapi import Header, HTTPException

from app.auth.tokens import bearer_token, verify


def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    claims = verify(bearer_token(authorization))
    if claims is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return {"id": claims["uid"]}
