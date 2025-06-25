from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

@dataclass
class User:
    uuid: str
    username: str
    email: str
    role: str
    access_level: str
    bucket_access: List[str]
    folder_access: List[str]
    upload_limit: int
    created_at: datetime
    last_login: Optional[datetime]
    status: str