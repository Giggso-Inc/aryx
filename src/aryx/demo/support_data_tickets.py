"""Ticket + resolution generation, mixed into SupportDataGenerator.

Split out of `demo/support_data_generator.py` (Raven Style Compliance
Plan, Phase 2b, 2026-09-03). Zero test patches — confirmed via grep.
"""
from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from aryx.demo.support_data_vocab import KB_ARTICLES, SOLUTION_TYPES, SYMPTOMS


class _TicketGenMixin:
    """Ticket + resolution generation, mixed into SupportDataGenerator."""

    def generate_tickets(self, site_ids: list[int], agent_ids: list[int]
                        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Generate 200 tickets + device links."""
        tickets = []
        links = []

        for i in range(self.ticket_count):
            site_id = random.choice(site_ids)
            priority = random.choices(
                ["low", "medium", "high", "critical"],
                weights=[20, 40, 30, 10],
            )[0]

            # Escalation logic: critical/high more likely to escalate
            escalate = (
                priority in ["critical", "high"]
                and random.random() < (0.7 if priority == "critical" else 0.4)
            )

            status = random.choices(
                ["open", "in_progress", "escalated", "resolved", "closed"],
                weights=[15, 25, (35 if escalate else 5), 20, 10],
            )[0]

            days_ago = random.randint(1, 90)
            created = self.now - timedelta(days=days_ago, hours=random.randint(0, 23))
            resolved = (
                created + timedelta(hours=random.randint(2, 48))
                if status in ["resolved", "closed"]
                else None
            )

            ticket = {
                "site_id": site_id,
                "created_by": f"user_{random.randint(1, 50)}@customer.com",
                "assigned_agent_id": random.choice(agent_ids) if random.random() > 0.1 else None,
                "status": status,
                "priority": priority,
                "symptom_text": random.choice(SYMPTOMS),
                "resolution_notes": (
                    "Resolved via firmware update" if status == "resolved"
                    else "Escalated to L3" if status == "escalated"
                    else None
                ),
                "resolved_at": resolved,
                "escalation_reason": (
                    "Hardware diagnostics inconclusive" if escalate
                    else None
                ),
                "created_at": created,
                "updated_at": resolved or created,
            }
            tickets.append(ticket)

            # Generate device links: 1–3 devices per ticket
            link_count = random.randint(1, 3)
            devices_for_site = [sid for sid, s_id in enumerate(site_ids) if s_id == site_id]
            # We'll set device_ids in a second pass after we know them
            # For now, store placeholder
            for _ in range(link_count):
                links.append({
                    "ticket_index": i,
                    "device_role": random.choice(["affected", "root_cause", "witness"]),
                })

        return tickets, links

    def generate_resolutions(self, ticket_count: int) -> list[dict[str, Any]]:
        """Generate resolution records for resolved tickets."""
        resolutions = []
        for ticket_id in range(1, ticket_count + 1):
            if random.random() < 0.6:  # 60% of tickets get a resolution
                solution_type = random.choice(SOLUTION_TYPES)
                resolutions.append({
                    "ticket_id": ticket_id,
                    "solution_type": solution_type,
                    "applied_by_agent_id": random.randint(1, 15),
                    "knowledge_link": (
                        random.choice(KB_ARTICLES)
                        if random.random() > 0.3
                        else None
                    ),
                    "success_flag": random.random() > 0.2,
                    "created_at": self.now - timedelta(days=random.randint(1, 30)),
                })
        return resolutions
