from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "thread" (
    "id" VARCHAR(32) NOT NULL  PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS "user" (
    "id" VARCHAR(32) NOT NULL  PRIMARY KEY,
    "secret" VARCHAR(32) NOT NULL UNIQUE,
    "created_at" TIMESTAMPTZ NOT NULL,
    "active" BOOL NOT NULL  DEFAULT True
);
CREATE INDEX IF NOT EXISTS "idx_user_secret_efba81" ON "user" ("secret");
CREATE TABLE IF NOT EXISTS "room" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "active" BOOL NOT NULL,
    "thread_id" VARCHAR(32) NOT NULL REFERENCES "thread" ("id") ON DELETE CASCADE,
    "user_id" VARCHAR(32) NOT NULL REFERENCES "user" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_room_user_id_c7c88a" UNIQUE ("user_id", "thread_id")
);
CREATE INDEX IF NOT EXISTS "idx_room_user_id_fed4e9" ON "room" ("user_id");
CREATE INDEX IF NOT EXISTS "idx_room_thread__c40394" ON "room" ("thread_id");
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSONB NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """
