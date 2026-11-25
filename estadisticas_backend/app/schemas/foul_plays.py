from pydantic import BaseModel, Field


class FoulPlayUpdate(BaseModel):
    shooter_game_player_id: int
    free_throws: int = Field(ge=1, le=3)
    closed: bool = False
