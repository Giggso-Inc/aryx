DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'aryx_shay_workspace_map_shay_workspace_id_fkey'
    ) THEN
        ALTER TABLE aryx_shay_workspace_map
        ADD CONSTRAINT aryx_shay_workspace_map_shay_workspace_id_fkey
        FOREIGN KEY (shay_workspace_id)
        REFERENCES gg_workspace(id)
        ON DELETE CASCADE
        NOT VALID;
    END IF;
END $$;
