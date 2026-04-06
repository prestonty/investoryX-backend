from pydantic import BaseModel


class EmailRequest(BaseModel):
    email: str
    first_name: str
    verification_url: str
