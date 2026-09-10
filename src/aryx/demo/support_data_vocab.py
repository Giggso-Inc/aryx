"""Realistic radio-equipment support vocabulary used by the demo data generator.

Split out of `demo/support_data_generator.py` (Raven Style Compliance
Plan, Phase 2b, 2026-09-03). Pure data, zero test patches — confirmed via
grep.
"""
from __future__ import annotations

CUSTOMERS = [
    ("NetOps Atlantic", "platinum"),
    ("Regional Wireless Co", "gold"),
    ("Metro Telecom", "gold"),
    ("Rural Comms Group", "silver"),
    ("Emergency Services Net", "platinum"),
    ("Industrial IoT Ops", "silver"),
    ("Federal Communications", "platinum"),
    ("Regional TV Broadcast", "gold"),
    ("Enterprise Mobility", "gold"),
    ("Utility Company A", "silver"),
]

SITES = {
    "HQ": ["New York", "Los Angeles", "Chicago", "Denver", "Atlanta"],
    "Remote": ["Seattle", "Phoenix", "Miami", "Boston", "Dallas", "San Francisco"],
    "Mobile": ["Unit-Mobile-01", "Unit-Mobile-02", "Unit-Mobile-03", "Unit-Mobile-04"],
}

DEVICE_MODELS = [
    "RadioX-6000", "RadioX-7000", "RadioX-9000",
    "WaveLink-200", "WaveLink-400", "WaveLink-600",
    "SectorMaster-2500", "SectorMaster-3000",
    "FieldOps-1000", "FieldOps-2000",
]

FIRMWARE_VERSIONS = ["6.2.1", "6.2.3", "6.3.0", "6.3.2", "7.0.0", "7.0.1"]

AGENTS = [
    ("Alex Chen", "L3", "Firmware"),
    ("Jordan Martinez", "L3", "Hardware"),
    ("Sam Patel", "L2", "Firmware"),
    ("Casey Brown", "L2", "Network"),
    ("Morgan Lee", "L2", "Configuration"),
    ("Taylor White", "L1", "General"),
    ("Riley Johnson", "L1", "General"),
    ("Alex Kim", "L1", "General"),
    ("Jordan Davis", "L2", "Hardware"),
    ("Casey Garcia", "L1", "General"),
    ("Morgan Wilson", "L3", "Network"),
    ("Taylor Anderson", "L2", "Configuration"),
    ("Riley Thomas", "L1", "General"),
    ("Alex Rodriguez", "L2", "Firmware"),
    ("Jordan Lopez", "L1", "General"),
]

EXPERTISE_TAGS = [
    "Firmware-6.2",
    "Firmware-7.0",
    "RMA-eligible",
    "Power-management",
    "Network-interference",
    "Configuration-advanced",
    "Hardware-debugging",
    "Field-certified",
]

SYMPTOMS = [
    "Device intermittent loss of signal",
    "Firmware crashes on boot",
    "Configuration memory corruption detected",
    "Network interface degradation",
    "Power supply instability",
    "Thermal shutdown triggered",
    "Cannot establish link with peer device",
    "Intermittent packet loss on uplink",
    "Device unresponsive to commands",
    "Frequent automatic reboot cycle",
    "Firmware update failed, device in recovery mode",
    "Radio frequency interference detected",
    "Device locked after failed authentication",
    "Memory usage spike, process crash",
    "Incorrect firmware version reported",
    "Device shows wrong configuration hash",
    "Cannot connect to management interface",
    "High CRC error rate on receive",
    "Backup power not activating",
    "Device reporting phantom alarms",
]

SOLUTION_TYPES = [
    "firmware_update",
    "config_push",
    "rma",
    "reboot",
    "documentation",
    "escalation",
]

KB_ARTICLES = [
    "https://kb.example.com/firmware-6.2-known-issues",
    "https://kb.example.com/thermal-management",
    "https://kb.example.com/network-tuning",
    "https://kb.example.com/rma-procedures",
    "https://kb.example.com/power-diagnostics",
    "https://kb.example.com/firmware-migration",
    "https://kb.example.com/interference-mitigation",
    "https://kb.example.com/device-recovery",
]
