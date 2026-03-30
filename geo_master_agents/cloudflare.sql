-- 1. 에이전트 메모리용 테이블 (checkpoints)
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    checkpoint TEXT NOT NULL,
    metadata TEXT NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_id)
);
CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT NOT NULL,
    blob TEXT NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_id, task_id, idx)
);

-- 2. 웹 서비스 갤러리 메타데이터용 테이블 (image_gallery)
CREATE TABLE IF NOT EXISTS image_gallery (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    image_url TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
