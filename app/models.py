from pydantic import BaseModel

class Submission(BaseModel):
    database: str
    commands: str
