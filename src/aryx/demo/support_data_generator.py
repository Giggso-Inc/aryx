"""Synthetic data generator for support demo — 200 realistic radio support tickets.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), the
vocabulary constants moved to `demo/support_data_vocab.py` and ticket +
resolution generation moved to `demo/support_data_tickets.py` (mixed into
this class as `_TicketGenMixin`). Zero whitebox test patches exist
anywhere against this module (confirmed via grep; it has a single
importer, `demo/loader.py`), so the split was purely mechanical.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from aryx.demo.support_data_tickets import _TicketGenMixin
from aryx.demo.support_data_vocab import (
    AGENTS,
    CUSTOMERS,
    DEVICE_MODELS,
    EXPERTISE_TAGS,
    FIRMWARE_VERSIONS,
    SITES,
)

__all__ = ["SupportDataGenerator"]


class SupportDataGenerator(_TicketGenMixin):
    """Generate realistic radio support ticket data."""

    def __init__(self, ticket_count: int = 200, seed: int | None = None):
        self.ticket_count = ticket_count
        if seed:
            random.seed(seed)
        self.now = datetime.utcnow()

    def generate_customers(self) -> list[dict[str, Any]]:
        """Generate 10 customers."""
        return [
            {
                "name": name,
                "sla_tier": tier,
                "primary_contact": f"contact@{name.lower().replace(' ', '')}.com",
                "created_at": self.now - timedelta(days=random.randint(30, 365)),
            }
            for name, tier in CUSTOMERS
        ]

    def generate_sites(self, customer_ids: list[int]) -> list[dict[str, Any]]:
        """Generate ~20 sites across customers."""
        sites = []
        for cid in customer_ids:
            site_types = list(SITES.keys())
            for _ in range(random.randint(1, 3)):
                site_type = random.choice(site_types)
                location = random.choice(SITES[site_type])
                sites.append({
                    "customer_id": cid,
                    "location": location,
                    "site_type": site_type,
                    "device_count": random.randint(5, 50),
                    "created_at": self.now - timedelta(days=random.randint(10, 365)),
                })
        return sites

    def generate_devices(self, site_ids: list[int]) -> list[dict[str, Any]]:
        """Generate ~150 devices across sites."""
        devices = []
        for sid in site_ids:
            count = random.randint(5, 20)
            for _ in range(count):
                devices.append({
                    "site_id": sid,
                    "model": random.choice(DEVICE_MODELS),
                    "firmware_version": random.choice(FIRMWARE_VERSIONS),
                    "config_hash": f"sha256_{random.randint(1000, 9999):04d}",
                    "install_date": (
                        self.now - timedelta(days=random.randint(30, 1000))
                    ).date(),
                    "status": random.choices(
                        ["active", "inactive", "degraded", "rma"],
                        weights=[70, 10, 15, 5],
                    )[0],
                    "last_heartbeat": (
                        self.now - timedelta(minutes=random.randint(1, 1440))
                        if random.random() > 0.2
                        else None
                    ),
                    "created_at": self.now - timedelta(days=random.randint(10, 365)),
                })
        return devices

    def generate_agents(self) -> list[dict[str, Any]]:
        """Generate 15 support agents."""
        return [
            {
                "name": name,
                "level": level,
                "specialty": specialty,
                "max_concurrent_tickets": 3 if level == "L3" else 5,
                "tickets_resolved": random.randint(10, 200),
                "created_at": self.now - timedelta(days=random.randint(30, 730)),
            }
            for name, level, specialty in AGENTS
        ]

    def generate_expertise_tags(self) -> list[dict[str, Any]]:
        """Generate expertise tags."""
        return [
            {"tag_name": tag, "description": f"Expertise in {tag}"}
            for tag in EXPERTISE_TAGS
        ]
