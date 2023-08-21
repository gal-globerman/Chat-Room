from tortoise import Tortoise, run_async


async def init():
    await Tortoise.init(
        db_url="postgres://postgres:Sfj39w@127.0.0.1:5432/postgres",
        modules={"models": ["db.models"]},
    )
    await Tortoise.generate_schemas()


run_async(init())
