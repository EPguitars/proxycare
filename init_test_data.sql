-- Add a test source
INSERT INTO public.sources (source) 
VALUES ('test_source')
ON CONFLICT (source) DO NOTHING;

-- Add a test provider
INSERT INTO public.providers (provider) 
VALUES ('test_provider')
ON CONFLICT (provider) DO NOTHING;

-- Add 5 test proxies with different priorities
-- First, get the IDs of our test source and provider
DO $$
DECLARE
    source_id INTEGER;
    provider_id INTEGER;
BEGIN
    -- Get the source ID
    SELECT id INTO source_id FROM public.sources WHERE source = 'test_source';
    
    -- Get the provider ID
    SELECT id INTO provider_id FROM public.providers WHERE provider = 'test_provider';
    
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
    INSERT INTO public.statistics (proxyId, counter, statusId)
    SELECT 
        p.id, 
        floor(random() * 100)::integer, 
        (ARRAY[200, 403, 404, 500])[floor(random() * 4 + 1)]
    FROM 
        public.proxies p
    WHERE 
        p.sourceId = source_id
    ON CONFLICT DO NOTHING;
END $$;

-- Verify the data was inserted
SELECT 'Test data has been initialized successfully!' AS message; 