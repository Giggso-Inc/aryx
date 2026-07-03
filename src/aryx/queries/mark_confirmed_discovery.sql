UPDATE aryx_discovery
SET status       = 'confirmed',
    confirmed_at = %s
WHERE discovery_id = %s
