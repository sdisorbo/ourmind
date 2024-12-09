CREATE TABLE IF NOT EXISTS images (
    id SERIAL PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_data BYTEA NOT NULL,
    date_uploaded TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS texts (
    id SERIAL PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_content TEXT NOT NULL,
    date_uploaded TIMESTAMP DEFAULT NOW()
);
