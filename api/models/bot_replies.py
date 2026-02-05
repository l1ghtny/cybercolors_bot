from pydantic import BaseModel


class ReplyAddModel(BaseModel):
    user_message: str
    bot_reply: str
    server_id: str
    admin_id: str