"""Kafka producer + topic bootstrap for the transaction stream."""

import json
import logging
from typing import Optional

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

from config import settings

logger = logging.getLogger("fraudshield.producer")

# 3 partitions -> up to 3 consumers can score in parallel; RF 1 (single dev broker).
_NUM_PARTITIONS = 3
_REPLICATION_FACTOR = 1

_producer: Optional[Producer] = None


def get_producer() -> Producer:
    """Lazily build the shared idempotent producer."""
    global _producer
    if _producer is None:
        _producer = Producer(
            {
                "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                # Durability: wait for in-sync replicas; dedup producer retries.
                "acks": "all",
                "enable.idempotence": True,
                "queue.buffering.max.ms": 50,
                "linger.ms": 5,
                "client.id": "fraudshield-producer",
            }
        )
    return _producer


def ensure_topics() -> None:
    """Idempotently create both topics (safe on every startup)."""
    admin = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})

    topics = [
        NewTopic(settings.KAFKA_TOPIC_RAW, _NUM_PARTITIONS, _REPLICATION_FACTOR),
        NewTopic(settings.KAFKA_TOPIC_SCORED, _NUM_PARTITIONS, _REPLICATION_FACTOR),
    ]
    futures = admin.create_topics(topics)

    for name, fut in futures.items():
        try:
            fut.result()
            logger.info("Created Kafka topic: %s", name)
        except Exception as exc:  # noqa: BLE001
            if "already exists" in str(exc).lower():
                logger.info("Kafka topic already exists: %s", name)
            else:
                logger.error("Failed to create topic %s: %s", name, exc)
                raise


def _delivery_report(err, msg) -> None:
    """Async delivery callback: logs the final fate of each produced record."""
    if err is not None:
        logger.error(
            "Delivery FAILED for key=%s: %s",
            msg.key().decode() if msg.key() else None,
            err,
        )
    else:
        logger.debug("Delivered to %s[%d]@%d", msg.topic(), msg.partition(), msg.offset())


def _produce(topic: str, key: str, value: dict) -> None:
    """Produce one JSON record keyed by `key` (non-blocking; retries once on a full queue)."""
    producer = get_producer()
    payload = json.dumps(value).encode("utf-8")
    encoded_key = key.encode("utf-8")

    try:
        producer.produce(topic, key=encoded_key, value=payload, on_delivery=_delivery_report)
    except BufferError:
        # Local queue full: serve callbacks to drain it, then retry once.
        producer.poll(1.0)
        producer.produce(topic, key=encoded_key, value=payload, on_delivery=_delivery_report)

    producer.poll(0)  # serve delivery callbacks without blocking


def publish_raw(message: dict) -> None:
    """Publish a transaction to transactions.raw, keyed by user_id for ordering."""
    _produce(settings.KAFKA_TOPIC_RAW, message["user_id"], message)


def publish_scored(message: dict) -> None:
    """Publish a scored result to transactions.scored, keyed by user_id."""
    _produce(settings.KAFKA_TOPIC_SCORED, message["user_id"], message)


def flush(timeout: float = 10.0) -> int:
    """Block until all buffered messages are delivered (or timeout). Returns # still queued."""
    if _producer is None:
        return 0
    return _producer.flush(timeout)


def close() -> None:
    """Flush and drop the producer reference on app shutdown."""
    global _producer
    if _producer is not None:
        remaining = _producer.flush(10.0)
        if remaining:
            logger.warning("Producer shut down with %d undelivered messages", remaining)
        _producer = None
