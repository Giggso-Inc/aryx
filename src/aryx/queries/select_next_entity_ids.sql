SELECT nextval(pg_get_serial_sequence('aryx_entity', 'id'))
FROM generate_series(1, %s)
