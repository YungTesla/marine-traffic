import asyncio
import logging
import signal
import sys

from src.ais_client import VesselPosition, VesselStatic, stream_ais
from src.encounter_detector import EncounterDetector
from src.water_client import poll_water_levels
from src import database as db
from src.config import STATS_INTERVAL_S

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

shutdown_event = asyncio.Event()


def handle_signal():
    logger.info("Shutdown signal received...")
    shutdown_event.set()


async def log_stats(detector: EncounterDetector):
    """Periodically log statistics."""
    while not shutdown_event.is_set():
        await asyncio.sleep(STATS_INTERVAL_S)
        s = detector.stats
        logger.info(
            "Stats: %d active vessels | %d active encounters | %d total encounters",
            s["active_vessels"], s["active_encounters"], s["total_encounters"],
        )


async def periodic_flush():
    """Periodically flush buffered positions to database."""
    buffer = db.get_buffer()
    while not shutdown_event.is_set():
        await asyncio.sleep(1)  # Check every second
        await buffer.auto_flush_if_needed()


async def run():
    db.init_db()
    detector = EncounterDetector()

    logger.info("Starting AIS encounter collector...")
    logger.info("Press Ctrl+C to stop.")

    stats_task = asyncio.create_task(log_stats(detector))
    flush_task = asyncio.create_task(periodic_flush())
    water_task = asyncio.create_task(poll_water_levels(shutdown_event))
    msg_count = 0

    try:
        async for msg in stream_ais():
            if shutdown_event.is_set():
                break

            if isinstance(msg, VesselPosition):
                await detector.update(msg)
                msg_count += 1
                if msg_count % 1000 == 0:
                    logger.info("Processed %d position messages", msg_count)

            elif isinstance(msg, VesselStatic):
                db.upsert_vessel(
                    msg.mmsi,
                    name=msg.name,
                    ship_type=msg.ship_type,
                    length=msg.length,
                    width=msg.width,
                )
    finally:
        logger.info("Flushing buffered positions...")
        await db.get_buffer().flush_all()

        stats_task.cancel()
        flush_task.cancel()
        water_task.cancel()

        s = detector.stats
        logger.info(
            "Shutting down. Final stats: %d vessels tracked, %d total encounters recorded.",
            s["active_vessels"], s["total_encounters"],
        )


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
