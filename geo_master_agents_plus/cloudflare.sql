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
DROP TABLE users; -- 개발 중인 경우, 기존 데이터를 초기화하기 위해 추가 (운영 시 제거)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE CHECK (email LIKE '%@%'),
    nickname TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_users_email ON users(email);

-- 3. 국가별 분야별 이슈 검색 현황 (issues)
DROP TABLE issues; -- 개발 중인 경우, 기존 데이터를 초기화하기 위해 추가 (운영 시 제거) 
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    country TEXT NOT NULL,
    year INTEGER NOT NULL,
    content TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_issues_country_domain_year ON issues(country, domain, year);
CREATE INDEX idx_issues_country ON issues(country);
CREATE INDEX idx_issues_domain ON issues(domain);
CREATE INDEX idx_issues_year ON issues(year);
CREATE INDEX idx_issues_user_id ON issues(user_id);

-- 4. 이슈별 카툰 이미지 생성 현황 (cartoons)
DROP TABLE cartoons; -- 개발 중인 경우, 기존 데이터를 초기화하기 위해 추가 (운영 시 제거) 
CREATE TABLE IF NOT EXISTS cartoons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt TEXT NOT NULL,
    image_url TEXT NOT NULL,
    issue_id INTEGER REFERENCES issues(id) ON DELETE CASCADE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_cartoons_prompt ON cartoons(prompt);
CREATE INDEX idx_cartoons_issue_id ON cartoons(issue_id);


-- 국가별 이슈 검색량 + 카툰 생성량
SELECT 
    i.country,
    COUNT(DISTINCT i.id) AS search_volume,
    COUNT(c.id) AS generation_volume
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
    COUNT(DISTINCT i.id) AS search_volume,
    COUNT(DISTINCT c.id) AS generation_volume
FROM 
    users u
LEFT JOIN 
    issues i ON u.id = i.user_id
LEFT JOIN 
    cartoons c ON i.id = c.issue_id
GROUP BY 
    u.id, u.nickname, u.email
ORDER BY 
    search_volume DESC, generation_volume DESC;
