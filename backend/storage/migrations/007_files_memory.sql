CREATE TABLE approved_folder (
 id TEXT PRIMARY KEY,
 path TEXT NOT NULL UNIQUE,
 device INTEGER NOT NULL,
 inode INTEGER NOT NULL,
 created_at TEXT NOT NULL,
 scanned_at TEXT,
 report_json TEXT
);
CREATE TABLE local_file (
 id TEXT PRIMARY KEY,
 root_id TEXT NOT NULL REFERENCES approved_folder(id) ON DELETE CASCADE,
 relative_path TEXT NOT NULL,
 name TEXT NOT NULL,
 device INTEGER NOT NULL,
 inode INTEGER NOT NULL,
 size INTEGER NOT NULL,
 modified_ns INTEGER NOT NULL,
 changed_ns INTEGER NOT NULL,
 sha256 TEXT,
 status TEXT NOT NULL,
 text TEXT NOT NULL,
 UNIQUE(root_id,relative_path)
);
CREATE VIRTUAL TABLE local_file_fts USING fts5(file_id UNINDEXED, name, text, tokenize='unicode61');
CREATE TRIGGER local_file_insert AFTER INSERT ON local_file BEGIN
 INSERT INTO local_file_fts(file_id,name,text) VALUES(new.id,new.name,new.text);
END;
CREATE TRIGGER local_file_update AFTER UPDATE ON local_file BEGIN
 DELETE FROM local_file_fts WHERE file_id=old.id;
 INSERT INTO local_file_fts(file_id,name,text) VALUES(new.id,new.name,new.text);
END;
CREATE TRIGGER local_file_delete AFTER DELETE ON local_file BEGIN
 DELETE FROM local_file_fts WHERE file_id=old.id;
END;
CREATE TABLE file_correction (
 id TEXT PRIMARY KEY,
 root_id TEXT NOT NULL REFERENCES approved_folder(id) ON DELETE CASCADE,
 query TEXT NOT NULL,
 file_id TEXT NOT NULL REFERENCES local_file(id) ON DELETE CASCADE,
 sha256 TEXT NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('wrong','preferred')),
 comment TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(root_id,query,file_id)
);
CREATE TABLE local_memory (
 id TEXT PRIMARY KEY,
 scope TEXT NOT NULL,
 kind TEXT NOT NULL,
 content TEXT NOT NULL,
 source TEXT NOT NULL,
 pinned INTEGER NOT NULL,
 expires_at TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 revision INTEGER NOT NULL
);
CREATE INDEX local_memory_scope ON local_memory(scope,updated_at DESC,id);
CREATE TABLE memory_request (
 idempotency_key TEXT PRIMARY KEY,
 request_hash TEXT NOT NULL,
 memory_id TEXT REFERENCES local_memory(id) ON DELETE SET NULL
);
