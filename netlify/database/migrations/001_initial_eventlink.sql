CREATE TABLE IF NOT EXISTS emails_cache (
  id SERIAL PRIMARY KEY,
  subject TEXT,
  sender TEXT,
  date TEXT,
  body TEXT,
  processed INTEGER DEFAULT 0,
  event_count INTEGER DEFAULT 0,
  fetched_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
  id SERIAL PRIMARY KEY,
  email_subject TEXT,
  email_from TEXT,
  email_date TEXT,
  email_body TEXT,
  event_name TEXT,
  date TEXT,
  time TEXT,
  venue TEXT,
  deadline TEXT,
  description TEXT,
  is_event INTEGER DEFAULT 1,
  user_response TEXT DEFAULT 'pending',
  calendar_link TEXT DEFAULT '',
  category TEXT DEFAULT 'general',
  priority TEXT DEFAULT 'optional',
  recommendation TEXT DEFAULT 'neutral',
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_interests (
  id SERIAL PRIMARY KEY,
  category TEXT NOT NULL,
  action TEXT NOT NULL,
  event_name TEXT,
  logged_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS emails_cache_subject_sender_idx ON emails_cache (subject, sender);
CREATE INDEX IF NOT EXISTS events_response_idx ON events (user_response);
CREATE INDEX IF NOT EXISTS events_category_idx ON events (category);
