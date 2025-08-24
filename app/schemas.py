from pydantic import BaseModel
from typing import Literal


class Submission(BaseModel):
    database: Literal["redis", "mongodb"]
    commands: str
