from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    ML_MODELS_DIR: str = "app/ml/models"
    MLB_POLL_INTERVAL: int = 10

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def DATABASE_URL_ASYNC(self) -> str:
        return self.DATABASE_URL.replace("pymysql", "aiomysql")


settings = Settings()
