UPDATE aryx_discovery
SET confirm_state = %s,
    status        = 'confirming'
WHERE discovery_id = %s
