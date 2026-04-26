from datetime import datetime
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"

    game_pk = Column(Integer, primary_key=True)
    game_date = Column(Date, nullable=False)
    home_team = Column(String(50))
    away_team = Column(String(50))
    status = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    pitches = relationship("Pitch", back_populates="game")


class Pitch(Base):
    __tablename__ = "pitches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_pk = Column(Integer, ForeignKey("games.game_pk"), nullable=False)
    at_bat_index = Column(Integer, nullable=False)
    pitch_number = Column(Integer, nullable=False)
    inning = Column(Integer)
    inning_half = Column(String(6))
    pitcher_id = Column(Integer)
    batter_id = Column(Integer)
    balls = Column(Integer)
    strikes = Column(Integer)
    outs = Column(Integer)
    on_1b = Column(Boolean, default=False)
    on_2b = Column(Boolean, default=False)
    on_3b = Column(Boolean, default=False)
    pitch_type = Column(String(30))
    zone = Column(Integer)
    result = Column(String(50))
    start_speed = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    game = relationship("Game", back_populates="pitches")
