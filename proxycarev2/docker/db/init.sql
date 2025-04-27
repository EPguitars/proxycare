-- This file will be automatically executed when the PostgreSQL container starts
-- Only handles table creation, not user insertion

-- Create schema tables
CREATE TABLE public.sources (
    id SERIAL PRIMARY KEY, 
    source VARCHAR(50) UNIQUE NOT NULL
);

CREATE TABLE public.providers (
    id SERIAL PRIMARY KEY, 
    provider VARCHAR(50) UNIQUE NOT NULL
);

CREATE TABLE public.statuses (
    statusCode INTEGER PRIMARY KEY, 
    shortDescription VARCHAR(300) UNIQUE NOT NULL
);

INSERT INTO public.statuses (statusCode, shortDescription) 
VALUES
(100, 'Continue'),
(101, 'Switching Protocols'),
(102, 'Processing'),
(103, 'Early Hints'),
(200, 'OK'),
(201, 'Created'),
(202, 'Accepted'),
(203, 'Non-Authoritative Information'),
(204, 'No Content'),
(205, 'Reset Content'),
(206, 'Partial Content'),
(207, 'Multi-Status'),
(208, 'Already Reported'),
(226, 'IM Used'),
(300, 'Multiple Choices'),
(301, 'Moved Permanently'),
(302, 'Found'),
(303, 'See Other'),
(304, 'Not Modified'),
(305, 'Use Proxy'),
(307, 'Temporary Redirect'),
(308, 'Permanent Redirect'),
(400, 'Bad Request'),
(401, 'Unauthorized'),
(402, 'Payment Required'),
(403, 'Forbidden'),
(404, 'Not Found'),
(405, 'Method Not Allowed'),
(406, 'Not Acceptable'),
(407, 'Proxy Authentication Required'),
(408, 'Request Timeout'),
(409, 'Conflict'),
(410, 'Gone'),
(411, 'Length Required'),
(412, 'Precondition Failed'),
(413, 'Payload Too Large'),
(414, 'URI Too Long'),
(415, 'Unsupported Media Type'),
(416, 'Range Not Satisfiable'),
(417, 'Expectation Failed'),
(418, 'Im a teapot'),
(421, 'Misdirected Request'),
(422, 'Unprocessable Entity'),
(423, 'Locked'),
(424, 'Failed Dependency'),
(425, 'Too Early'),
(426, 'Upgrade Required'),
(428, 'Precondition Required'),
(429, 'Too Many Requests'),
(431, 'Request Header Fields Too Large'),
(451, 'Unavailable For Legal Reasons'),
(500, 'Internal Server Error'),
(501, 'Not Implemented'),
(502, 'Bad Gateway'),
(503, 'Service Unavailable'),
(504, 'Gateway Timeout'),
(505, 'HTTP Version Not Supported'),
(506, 'Variant Also Negotiates'),
(507, 'Insufficient Storage'),
(508, 'Loop Detected'),
(510, 'Not Extended'),
(511, 'Network Authentication Required');

CREATE TABLE public.proxies (
    id SERIAL PRIMARY KEY,
    proxy VARCHAR(100) NOT NULL,
    sourceId INTEGER REFERENCES public.sources(id),
    priority INTEGER,
    blocked BOOLEAN,
    provider INTEGER REFERENCES public.providers(id),
    usage_interval INTEGER DEFAULT 30,
    updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.statistics (
    id SERIAL PRIMARY KEY,
    proxyId INTEGER REFERENCES public.proxies(id),
    statusId INTEGER REFERENCES public.statuses(statusCode)
);

-- Functions and triggers
CREATE OR REPLACE FUNCTION update_timestamp_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updatedAt := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_timestamp_trigger
BEFORE INSERT OR UPDATE ON proxies
FOR EACH ROW
EXECUTE FUNCTION update_timestamp_column();

-- Function for update blocked values
CREATE OR REPLACE FUNCTION update_blocked_status() RETURNS VOID AS $$
BEGIN
    UPDATE proxies AS t
    SET blocked = FALSE
    FROM (
        SELECT DISTINCT ON (sourceid)
               sourceid,
               updatedat
        FROM proxies
        WHERE updatedat < NOW() - INTERVAL '5 minutes'
        ORDER BY sourceid, updatedat DESC
    ) AS t2
    WHERE t.sourceid = t2.sourceid;
END;
$$ LANGUAGE plpgsql;

-- Add a test source
INSERT INTO public.sources (source) 
VALUES ('test_source')
ON CONFLICT (source) DO NOTHING;

-- Add a test provider
INSERT INTO public.providers (provider) 
VALUES ('test_provider')
ON CONFLICT (provider) DO NOTHING;

-- Add 5 test proxies with different priorities
DO $$
DECLARE
    source_id INTEGER;
    provider_id INTEGER;
    status_codes INTEGER[] := ARRAY[200, 403, 404, 500];
    random_idx INTEGER;
BEGIN
    -- Get the source ID
    SELECT id INTO source_id FROM public.sources WHERE source = 'test_source';
    
    -- Get the provider ID
    SELECT id INTO provider_id FROM public.providers WHERE provider = 'test_provider';
    
    RAISE NOTICE 'Source ID: %, Provider ID: %', source_id, provider_id;
    
    IF source_id IS NULL OR provider_id IS NULL THEN
        RAISE EXCEPTION 'Source or provider ID is NULL';
    END IF;
    
    -- Insert test proxies
    INSERT INTO public.proxies (proxy, sourceId, priority, blocked, provider)
    VALUES 
        ('192.168.1.1:8080', source_id, 100, false, provider_id),
        ('192.168.1.2:8080', source_id, 90, false, provider_id),
        ('192.168.1.3:8080', source_id, 80, false, provider_id),
        ('192.168.1.4:8080', source_id, 70, false, provider_id),
        ('192.168.1.5:8080', source_id, 60, false, provider_id)
    ON CONFLICT DO NOTHING;
    
    -- Add some statistics for these proxies
    FOR i IN 1..5 LOOP
        -- Generate a safe random index (1-4)
        random_idx := 1 + floor(random() * 4);
        IF random_idx > 4 THEN random_idx := 4; END IF;
        
        INSERT INTO public.statistics (proxyId, counter, statusId)
        SELECT 
            p.id, 
            floor(random() * 100)::integer, 
            status_codes[random_idx]
        FROM 
            public.proxies p
        WHERE 
            p.proxy = '192.168.1.' || i || ':8080'
        ON CONFLICT DO NOTHING;
    END LOOP;
    
    RAISE NOTICE 'Initialization completed successfully';
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Error during initialization: %', SQLERRM;
END $$;

-- Create tables required by our API
CREATE TABLE IF NOT EXISTS public.users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS public.tokens (
    id SERIAL PRIMARY KEY,
    token VARCHAR(255) UNIQUE NOT NULL,
    user_id INTEGER REFERENCES public.users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Add a trigger to update the updated_at field in the users table
CREATE OR REPLACE FUNCTION update_user_timestamp_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_user_timestamp_trigger
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION update_user_timestamp_column();

-- Note: User creation has been moved to the application (init_db.py) 