UPDATE aryx_discovery
SET confirm_state = %s,
    status        = 'partial'
WHERE discovery_id = %s
