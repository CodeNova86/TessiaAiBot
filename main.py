import asyncio

from father_gateway import main as father_gateway_main
from tessia_bot.bot import main as tessia_bot_main
from tessia_bot.logging_utils import get_logger, setup_logging


logger = get_logger("main")


async def run_service(name, runner):
    logger.info("Starting service: %s", name)
    try:
        await runner()
    except asyncio.CancelledError:
        logger.info("Service cancelled: %s", name)
        raise
    except Exception:
        logger.exception("Service crashed: %s", name)
        raise


async def main():
    setup_logging()
    logger.info("Booting Tessia stack")
    await asyncio.gather(
        run_service("tessia_bot", tessia_bot_main),
        run_service("father_gateway", father_gateway_main),
    )


if __name__ == "__main__":
    asyncio.run(main())
