
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        username TEXT,
        timezone_name TEXT NOT NULL DEFAULT 'Europe/London',
        calendar_color TEXT NOT NULL DEFAULT '#8a74ff',
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS user_vaults (
        user_id BIGINT PRIMARY KEY,
        envelope_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS families (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        owner_id BIGINT NOT NULL,
        invite_code TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        FOREIGN KEY(owner_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS family_members (
        family_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL,
        role TEXT NOT NULL DEFAULT 'parent',
        joined_at TEXT NOT NULL,
        PRIMARY KEY(family_id, user_id),
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS family_invites (
        lookup_hash TEXT PRIMARY KEY,
        family_id BIGINT NOT NULL,
        created_by BIGINT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS family_invites_family_idx ON family_invites(family_id);
    CREATE TABLE IF NOT EXISTS children (
        id BIGSERIAL PRIMARY KEY,
        family_id BIGINT NOT NULL,
        name TEXT NOT NULL,
        birthday TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS messages (
        id BIGSERIAL PRIMARY KEY,
        family_id BIGINT NOT NULL,
        sender_id BIGINT NOT NULL,
        body TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        record_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(sender_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS message_reads (
        message_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL,
        read_at TEXT NOT NULL,
        PRIMARY KEY(message_id, user_id),
        FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS typing_status (
        family_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL,
        expires_at BIGINT NOT NULL,
        PRIMARY KEY(family_id, user_id),
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS messages_family_id_idx ON messages(family_id, id);
    CREATE INDEX IF NOT EXISTS message_reads_user_idx ON message_reads(user_id, message_id);
    CREATE TABLE IF NOT EXISTS events (
        id BIGSERIAL PRIMARY KEY,
        family_id BIGINT NOT NULL,
        creator_id BIGINT NOT NULL,
        title TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'general',
        start_at TEXT NOT NULL,
        end_at TEXT,
        notes TEXT,
        reminder_minutes BIGINT NOT NULL DEFAULT 0,
        recurrence TEXT NOT NULL DEFAULT 'none',
        recurrence_until TEXT,
        timezone_offset BIGINT NOT NULL DEFAULT 0,
        timezone_name TEXT NOT NULL DEFAULT 'Europe/London',
        cancelled_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(creator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS handovers (
        id BIGSERIAL PRIMARY KEY,
        family_id BIGINT NOT NULL,
        creator_id BIGINT NOT NULL,
        title TEXT NOT NULL,
        scheduled_at TEXT NOT NULL,
        location TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        response_note TEXT,
        timezone_name TEXT NOT NULL DEFAULT 'Europe/London',
        completed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(creator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS decisions (
        id BIGSERIAL PRIMARY KEY,
        family_id BIGINT NOT NULL,
        creator_id BIGINT NOT NULL,
        title TEXT NOT NULL,
        details TEXT,
        deadline TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        response_note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(creator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS expenses (
        id BIGSERIAL PRIMARY KEY,
        family_id BIGINT NOT NULL,
        creator_id BIGINT NOT NULL,
        title TEXT NOT NULL,
        amount_pence BIGINT NOT NULL,
        split_percent BIGINT NOT NULL DEFAULT 50,
        due_date TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        receipt_path TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(creator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS rules (
        id BIGSERIAL PRIMARY KEY,
        family_id BIGINT NOT NULL,
        creator_id BIGINT NOT NULL,
        title TEXT NOT NULL,
        rule_type TEXT NOT NULL DEFAULT 'custom',
        value_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(creator_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS audit (
        id BIGSERIAL PRIMARY KEY,
        family_id BIGINT NOT NULL,
        user_id BIGINT,
        event_type TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id BIGINT,
        summary TEXT NOT NULL,
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id BIGSERIAL PRIMARY KEY,
        family_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL,
        actor_id BIGINT,
        notification_type TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT,
        target_type TEXT,
        target_id BIGINT,
        target_value TEXT,
        dedupe_key TEXT,
        created_at TEXT NOT NULL,
        read_at TEXT,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(actor_id) REFERENCES users(id),
        UNIQUE(user_id, dedupe_key)
    );
    CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications(user_id, read_at, id);
    CREATE TABLE IF NOT EXISTS feature_requests (
        id BIGSERIAL PRIMARY KEY,
        family_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS feature_requests_created_idx ON feature_requests(created_at, id);

CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_idx ON users(lower(email));
CREATE UNIQUE INDEX IF NOT EXISTS users_username_idx ON users(lower(username)) WHERE username IS NOT NULL;

CREATE TABLE IF NOT EXISTS app_migrations (
    name TEXT PRIMARY KEY,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE FUNCTION protect_record() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='UPDATE' AND current_setting('parenting.vault_migration', true)='on' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Saved records cannot be changed' USING ERRCODE='23514';
END;
$$;
DROP TRIGGER IF EXISTS messages_no_change ON messages;
CREATE TRIGGER messages_no_change BEFORE UPDATE OR DELETE ON messages
FOR EACH ROW EXECUTE FUNCTION protect_record();
DROP TRIGGER IF EXISTS audit_no_change ON audit;
CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit
FOR EACH ROW EXECUTE FUNCTION protect_record();

-- Notifications are transactional: rolled-back writes never reach subscribers.
-- Payloads contain routing metadata only, never message text or encryption keys.
CREATE OR REPLACE FUNCTION notify_family_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE fid BIGINT;
BEGIN
    IF TG_TABLE_NAME='message_reads' THEN
        SELECT family_id INTO fid FROM messages WHERE id=NEW.message_id;
    ELSE
        IF TG_OP='DELETE' THEN fid=OLD.family_id; ELSE fid=NEW.family_id; END IF;
    END IF;
    PERFORM pg_notify('parenting_live', json_build_object('family_id', fid, 'table', TG_TABLE_NAME)::text);
    RETURN NULL;
END;
$$;
DO $$
DECLARE tab TEXT;
BEGIN
    FOREACH tab IN ARRAY ARRAY['messages','message_reads','typing_status','events','handovers',
                               'decisions','expenses','rules','children','audit','notifications','family_members'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS live_change ON %I', tab);
        EXECUTE format('CREATE TRIGGER live_change AFTER INSERT OR UPDATE OR DELETE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION notify_family_change()', tab);
    END LOOP;
END;
$$;
