import type { Config } from "@netlify/functions";
import { getDatabase } from "@netlify/database";
import { ImapFlow } from "imapflow";
import { simpleParser } from "mailparser";

type EventRow = {
  id: number;
  event_name: string | null;
  date: string | null;
  time: string | null;
  venue: string | null;
  description: string | null;
  category: string | null;
  priority: string | null;
  user_response: string | null;
};

const json = (data: unknown, init: ResponseInit = {}) =>
  Response.json(data, {
    ...init,
    headers: {
      "cache-control": "no-store",
      ...(init.headers || {}),
    },
  });

const textOrEmpty = (value: unknown) => (typeof value === "string" ? value.trim() : "");

const query = async (strings: TemplateStringsArray, ...values: unknown[]) => {
  const db = getDatabase();
  return db.sql(strings, ...values);
};

const extractEvent = (subject: string, body: string) => {
  const content = `${subject}\n${body}`.replace(/\s+/g, " ").trim();
  const eventWords = /\b(event|meeting|seminar|workshop|webinar|deadline|registration|interview|exam|lecture|session|orientation|conference|hackathon|drive|camp|fest)\b/i;
  if (!eventWords.test(content)) return null;

  const dateMatch = content.match(/\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+\d{1,2}(?:,\s*\d{4})?\b/i)
    || content.match(/\b\d{4}-\d{2}-\d{2}\b/)
    || content.match(/\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b/);
  const timeMatch = content.match(/\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b/i) || content.match(/\b\d{1,2}:\d{2}\b/);
  const venueMatch = content.match(/\b(?:at|venue:|location:)\s+([^.;,\n]{3,80})/i);
  const deadlineMatch = content.match(/\b(?:deadline|last date|register by)[:\s-]+([^.;\n]{3,80})/i);
  const lowered = content.toLowerCase();
  const category = lowered.match(/interview|placement|internship|career|drive/) ? "placements"
    : lowered.match(/exam|lecture|assignment|seminar|workshop|course/) ? "academics"
    : lowered.match(/fee|scholarship|stipend|payment/) ? "finance"
    : lowered.match(/health|counselling|wellness|gym/) ? "wellness"
    : lowered.match(/club|fest|sports|competition|hackathon/) ? "clubs"
    : lowered.match(/meeting|committee/) ? "meetings"
    : "general";
  const priority = lowered.match(/urgent|tomorrow|deadline|last date|interview|exam/) ? "urgent"
    : lowered.match(/important|compulsory|required|within a week/) ? "important"
    : "optional";

  return {
    event_name: subject || "Untitled event",
    date: dateMatch?.[0] || "",
    time: timeMatch?.[0] || "",
    venue: venueMatch?.[1]?.trim() || "",
    deadline: deadlineMatch?.[1]?.trim() || "",
    description: content.slice(0, 220),
    category,
    priority,
  };
};

const processPendingEmails = async () => {
  const rows = await query`SELECT * FROM emails_cache WHERE processed = 0 ORDER BY id ASC LIMIT 25`;
  for (const row of rows as any[]) {
    const event = extractEvent(row.subject || "", row.body || "");
    if (event) {
      await query`
        INSERT INTO events (
          email_subject, email_from, email_date, email_body, event_name, date, time,
          venue, deadline, description, is_event, user_response, calendar_link,
          category, priority, recommendation, created_at
        )
        VALUES (
          ${row.subject || ""}, ${row.sender || ""}, ${row.date || ""}, ${row.body || ""},
          ${event.event_name}, ${event.date}, ${event.time}, ${event.venue}, ${event.deadline},
          ${event.description}, ${1}, ${"pending"}, ${""}, ${event.category}, ${event.priority},
          ${"neutral"}, NOW()
        )
      `;
      await query`UPDATE emails_cache SET processed = 1, event_count = 1 WHERE id = ${row.id}`;
    } else {
      await query`UPDATE emails_cache SET processed = 1, event_count = 0 WHERE id = ${row.id}`;
    }
  }
};

const fetchEmails = async () => {
  const host = process.env.IMAP_HOST;
  const port = Number(process.env.IMAP_PORT || "993");
  const user = process.env.IMAP_USER;
  const pass = process.env.IMAP_PASSWORD;
  if (!host || !user || !pass) {
    return { error: "Set IMAP_HOST, IMAP_PORT, IMAP_USER, and IMAP_PASSWORD environment variables to fetch email." };
  }

  const client = new ImapFlow({ host, port, secure: true, auth: { user, pass }, logger: false });
  await client.connect();
  const lock = await client.getMailboxLock("INBOX");
  try {
    const mailbox = client.mailbox;
    const total = mailbox && typeof mailbox === "object" ? mailbox.exists || 0 : 0;
    const start = Math.max(1, total - 19);
    const messages = [];
    for await (const msg of client.fetch(`${start}:*`, { envelope: true, source: true })) {
      const parsed = await simpleParser(msg.source);
      messages.push({
        subject: parsed.subject || "(no subject)",
        sender: parsed.from?.text || "",
        date: parsed.date?.toISOString() || msg.envelope?.date?.toISOString?.() || "",
        body: parsed.text || parsed.html?.replace(/<[^>]*>/g, " ") || "",
      });
    }
    messages.reverse();

    let inserted = 0;
    for (const em of messages) {
      const existing = await query`SELECT id FROM emails_cache WHERE subject = ${em.subject} AND sender = ${em.sender} LIMIT 1`;
      if ((existing as any[]).length) continue;
      await query`
        INSERT INTO emails_cache (subject, sender, date, body, processed, event_count, fetched_at)
        VALUES (${em.subject}, ${em.sender}, ${em.date}, ${em.body}, ${0}, ${0}, NOW())
      `;
      inserted += 1;
    }
    await processPendingEmails();
    return { fetched: messages.length, new: inserted };
  } finally {
    lock.release();
    await client.logout();
  }
};

const parseEventDate = (event: EventRow) => {
  const combined = `${event.date || ""} ${event.time || ""}`.trim();
  const timestamp = combined ? Date.parse(combined) : Number.NaN;
  return Number.isNaN(timestamp) ? null : new Date(timestamp);
};

export default async (req: Request) => {
  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/api\/?/, "");

  try {
    if (path === "status" && req.method === "GET") {
      const [emailCount] = await query`SELECT COUNT(*)::int AS count FROM emails_cache`;
      const [eventCount] = await query`SELECT COUNT(*)::int AS count FROM events WHERE is_event = 1`;
      const [pending] = await query`SELECT COUNT(*)::int AS count FROM emails_cache WHERE processed = 0`;
      const [onCalendar] = await query`SELECT COUNT(*)::int AS count FROM events WHERE calendar_link != ''`;
      return json({
        accounts: process.env.IMAP_USER ? 1 : 0,
        emails_cached: (emailCount as any).count,
        events_extracted: (eventCount as any).count,
        pending_processing: (pending as any).count,
        on_calendar: (onCalendar as any).count,
        ollama_running: false,
      });
    }

    if (path === "fetch-emails" && req.method === "POST") {
      const result = await fetchEmails();
      return "error" in result ? json(result, { status: 400 }) : json(result);
    }

    if (path === "emails" && req.method === "GET") {
      const rows = await query`SELECT id, subject, sender, date, body, processed, event_count FROM emails_cache ORDER BY id DESC LIMIT 30`;
      return json(rows);
    }

    if (path === "events" && req.method === "GET") {
      const filter = url.searchParams.get("filter") || "all";
      const category = url.searchParams.get("category") || "all";
      const priority = url.searchParams.get("priority") || "all";
      const rows = await query`
        SELECT * FROM events
        WHERE is_event = 1
          AND (${filter} = 'all' OR (${filter} = 'pending' AND user_response = 'pending') OR (${filter} = 'attending' AND user_response = 'attend'))
          AND (${category} = 'all' OR category = ${category})
          AND (${priority} = 'all' OR priority = ${priority})
        ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'important' THEN 2 ELSE 3 END, id DESC
      `;
      return json(rows);
    }

    if (path === "summary" && req.method === "GET") {
      const [total] = await query`SELECT COUNT(*)::int AS count FROM events WHERE is_event = 1`;
      const [urgent] = await query`SELECT COUNT(*)::int AS count FROM events WHERE is_event = 1 AND priority = 'urgent'`;
      const [important] = await query`SELECT COUNT(*)::int AS count FROM events WHERE is_event = 1 AND priority = 'important'`;
      const [attending] = await query`SELECT COUNT(*)::int AS count FROM events WHERE is_event = 1 AND user_response = 'attend'`;
      const [pending] = await query`SELECT COUNT(*)::int AS count FROM events WHERE is_event = 1 AND user_response = 'pending'`;
      const categories = await query`SELECT category, COUNT(*)::int AS cnt FROM events WHERE is_event = 1 GROUP BY category ORDER BY cnt DESC`;
      const byCategory = Object.fromEntries((categories as any[]).map((row) => [row.category || "general", row.cnt]));
      const parts = [];
      if ((urgent as any).count) parts.push(`${(urgent as any).count} urgent`);
      if ((important as any).count) parts.push(`${(important as any).count} important`);
      for (const row of (categories as any[]).slice(0, 2)) parts.push(`${row.cnt} ${row.category || "general"}`);
      if ((attending as any).count) parts.push(`${(attending as any).count} attending`);
      if ((pending as any).count) parts.push(`${(pending as any).count} awaiting response`);
      return json({
        sentence: parts.length ? parts.join("  ·  ") : "No events yet",
        total: (total as any).count,
        urgent: (urgent as any).count,
        important: (important as any).count,
        attending: (attending as any).count,
        pending: (pending as any).count,
        by_category: byCategory,
      });
    }

    const responseMatch = path.match(/^events\/(\d+)\/response$/);
    if (responseMatch && req.method === "PATCH") {
      const id = Number(responseMatch[1]);
      const body = await req.json();
      const response = textOrEmpty(body.response);
      if (!["attend", "dismiss", "pending"].includes(response)) return json({ error: "Invalid response" }, { status: 400 });
      await query`UPDATE events SET user_response = ${response} WHERE id = ${id}`;
      if (response !== "pending") {
        const [event] = await query`SELECT event_name, category FROM events WHERE id = ${id}`;
        if (event) {
          await query`
            INSERT INTO user_interests (category, action, event_name, logged_at)
            VALUES (${(event as any).category || "general"}, ${response}, ${(event as any).event_name || ""}, NOW())
          `;
        }
      }
      return json({ ok: true, id, response });
    }

    const calendarMatch = path.match(/^events\/(\d+)\/add-to-calendar$/);
    if (calendarMatch && req.method === "POST") {
      const id = Number(calendarMatch[1]);
      await query`UPDATE events SET user_response = 'attend' WHERE id = ${id}`;
      return json({
        ok: false,
        error: "Google Calendar server-side OAuth is not configured for Netlify yet. The event was marked as attending.",
      }, { status: 501 });
    }

    if (path === "process" && req.method === "POST") {
      await processPendingEmails();
      return json({ ok: true });
    }

    if (path === "interests" && req.method === "GET") {
      const scores = await query`
        SELECT category,
          SUM(CASE WHEN action = 'attend' THEN 2 ELSE 0 END) - SUM(CASE WHEN action = 'dismiss' THEN 1 ELSE 0 END)::int AS score,
          COUNT(*)::int AS total
        FROM user_interests
        GROUP BY category
        ORDER BY score DESC
      `;
      const history = await query`SELECT category, action, event_name, logged_at FROM user_interests ORDER BY logged_at DESC LIMIT 20`;
      const interests = Object.fromEntries((scores as any[]).map((row) => [row.category, { score: row.score, total: row.total }]));
      return json({
        interests,
        liked: (scores as any[]).filter((row) => row.score >= 2).map((row) => row.category),
        disliked: (scores as any[]).filter((row) => row.score < 0).map((row) => row.category),
        history,
        has_data: (history as any[]).length > 0,
      });
    }

    if (path === "notifications" && req.method === "GET") {
      const rows = await query`SELECT id, event_name, date, time, venue, description, category, priority, user_response FROM events WHERE is_event = 1 AND user_response = 'attend' ORDER BY id DESC`;
      const now = Date.now();
      const notifications = (rows as EventRow[]).flatMap((event) => {
        const eventDate = parseEventDate(event);
        if (!eventDate) {
          return [{ ...event, urgency: "upcoming", time_label: event.date ? `Upcoming · ${event.date}` : "Date not set" }];
        }
        const diffMin = Math.round((eventDate.getTime() - now) / 60000);
        if (diffMin < 0) return [];
        if (diffMin <= 10) return [{ ...event, urgency: "now", time_label: `Starting in ${diffMin} min` }];
        if (diffMin <= 60) return [{ ...event, urgency: "soon", time_label: `In ${diffMin} minutes` }];
        if (diffMin <= 1440) return [{ ...event, urgency: "today", time_label: `Today in ${Math.floor(diffMin / 60)}h ${diffMin % 60}m` }];
        return [{ ...event, urgency: "upcoming", time_label: `In ${Math.floor(diffMin / 1440)} day${diffMin >= 2880 ? "s" : ""}` }];
      });
      return json(notifications);
    }

    return json({ error: "Not found" }, { status: 404 });
  } catch (error) {
    return json({ error: error instanceof Error ? error.message : "Unexpected error" }, { status: 500 });
  }
};

export const config: Config = {
  path: "/api/*",
};
