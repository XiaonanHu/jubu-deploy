-- LISTEN/NOTIFY trigger for Phase 2 live conversation viewer.
--
-- Fires pg_notify('turn_inserted', conversation_id) after every INSERT on
-- conversation_turns so the stats_api SSE service can push turns to browsers
-- in real time without polling.
--
-- On existing deployments this only runs once, on fresh volume creation.
-- To apply manually on a running instance:
--   docker exec -i postgres psql -U jubu -d jubu < postgres/init/02-turn-notify-trigger.sql

CREATE OR REPLACE FUNCTION notify_turn_inserted()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('turn_inserted', NEW.conversation_id);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_turn_inserted ON conversation_turns;

CREATE TRIGGER trg_turn_inserted
AFTER INSERT ON conversation_turns
FOR EACH ROW EXECUTE FUNCTION notify_turn_inserted();
