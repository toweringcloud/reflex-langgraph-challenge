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

-- 2. 방문 유저 현황 (users)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE CHECK (email LIKE '%@%'),
    nickname TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 3. 국가별 분야별 이슈 검색 현황 (issues)
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    country TEXT NOT NULL,
    year INTEGER NOT NULL,
    content TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_issues_country ON issues(country);
CREATE INDEX idx_issues_domain ON issues(domain);
CREATE INDEX idx_issues_year ON issues(year);
CREATE INDEX idx_issues_user_id ON issues(user_id);

-- 4. 이슈별 카툰 이미지 생성 현황 (cartoons)
CREATE TABLE IF NOT EXISTS cartoons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt TEXT NOT NULL,
    image_url TEXT NOT NULL,
    issue_id INTEGER REFERENCES issues(id) ON DELETE CASCADE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_cartoons_issue_id ON cartoons(issue_id);


-- 국가별 이슈 검색량 + 카툰 생성량
SELECT 
    i.country,
    COUNT(DISTINCT i.id) AS search_volume,    -- 국가별 이슈 검색 횟수
    COUNT(c.id) AS generation_volume          -- 국가별 카툰 생성 횟수
FROM 
    issues i
LEFT JOIN 
    cartoons c ON i.id = c.issue_id
GROUP BY 
    i.country;

-- 유저별 이슈 검색량 + 카툰 생성량
SELECT 
    u.id AS user_id,
    u.nickname,
    u.email,
    COUNT(DISTINCT i.id) AS search_volume,    -- 유저별 이슈 검색 횟수
    COUNT(DISTINCT c.id) AS generation_volume -- 유저별 카툰 생성 횟수
FROM 
    users u
LEFT JOIN 
    issues i ON u.id = i.user_id
LEFT JOIN 
    cartoons c ON i.id = c.issue_id
GROUP BY 
    u.id, u.nickname, u.email
ORDER BY 
    search_volume DESC, generation_volume DESC; -- 활동량이 많은 유저부터 정렬
