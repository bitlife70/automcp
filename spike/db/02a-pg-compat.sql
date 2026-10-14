-- PostgreSQL 호환 보정: 도메인 객체가 java.time.LocalDateTime을 쓰므로
-- PG JDBC 드라이버가 DATE → LocalDateTime 변환을 거부한다(HSQLDB는 허용). 앱 코드는 그대로 두고 컬럼 타입만 맞춘다.
ALTER TABLE orders      ALTER COLUMN orderdate TYPE timestamp;
ALTER TABLE orderstatus ALTER COLUMN "timestamp" TYPE timestamp;
