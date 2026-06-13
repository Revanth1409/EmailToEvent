import os
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES           = ['https://www.googleapis.com/auth/calendar.events']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE       = 'calendar_token.json'


# ──────────────────────────────────────────────
#  AUTH
# ──────────────────────────────────────────────
def get_calendar_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError("credentials.json not found. Download it from Google Cloud Console.")
            flow  = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)


# ──────────────────────────────────────────────
#  DATE / TIME PARSING
# ──────────────────────────────────────────────
def parse_event_datetime(date_str, time_str):
    date_str = (date_str or "").strip()
    time_str = (time_str or "").strip()

    date_formats = [
        "%B %d, %Y", "%b %d, %Y", "%d %B %Y",
        "%Y-%m-%d",  "%d/%m/%Y",  "%m/%d/%Y",
        "%d-%m-%Y",  "%B %d",     "%b %d",
    ]
    parsed_date = None
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            if parsed_date.year == 1900:
                parsed_date = parsed_date.replace(year=datetime.now().year)
            break
        except ValueError:
            continue
    if parsed_date is None:
        parsed_date = datetime.now() + timedelta(days=1)

    # Handle time ranges — take start time only
    if '–' in time_str or '-' in time_str:
        time_str = time_str.replace('–', '-').split('-')[0].strip()
    for tz in ['EST','IST','GMT','UTC','PST','CST','MST']:
        time_str = time_str.replace(tz, '').strip()

    time_formats = ["%I:%M %p", "%I:%M%p", "%H:%M", "%I %p"]
    parsed_time  = None
    for fmt in time_formats:
        try:
            parsed_time = datetime.strptime(time_str, fmt)
            break
        except ValueError:
            continue

    if parsed_time:
        start_dt = parsed_date.replace(hour=parsed_time.hour, minute=parsed_time.minute, second=0, microsecond=0)
        end_dt   = start_dt + timedelta(hours=1)
        all_day  = False
    else:
        start_dt = parsed_date.replace(hour=9, minute=0, second=0, microsecond=0)
        end_dt   = start_dt + timedelta(hours=1)
        all_day  = True

    return start_dt, end_dt, all_day


# ──────────────────────────────────────────────
#  CREATE CALENDAR EVENT
# ──────────────────────────────────────────────
def add_event_to_calendar(event_name, date_str, time_str, venue, description):
    try:
        service  = get_calendar_service()
        start_dt, end_dt, all_day = parse_event_datetime(date_str, time_str)

        full_desc = (description or "") + "\n\nAdded by EventLink"

        if all_day:
            event_body = {
                'summary':     event_name,
                'location':    venue or "",
                'description': full_desc,
                'start': {'date': start_dt.strftime("%Y-%m-%d")},
                'end':   {'date': end_dt.strftime("%Y-%m-%d")},
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 30},
                        {'method': 'email', 'minutes': 60},
                    ]
                }
            }
        else:
            offset    = "+05:30"   # IST for IITM
            start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S") + offset
            end_str   = end_dt.strftime("%Y-%m-%dT%H:%M:%S")   + offset
            event_body = {
                'summary':     event_name,
                'location':    venue or "",
                'description': full_desc,
                'start': {'dateTime': start_str, 'timeZone': 'Asia/Kolkata'},
                'end':   {'dateTime': end_str,   'timeZone': 'Asia/Kolkata'},
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 5},    # 5-min reminder
                        {'method': 'email', 'minutes': 60},   # 1-hr email heads-up
                    ]
                }
            }

        created = service.events().insert(calendarId='primary', body=event_body).execute()
        return {
            'success':       True,
            'calendar_link': created.get('htmlLink', ''),
            'event_id':      created.get('id', ''),
            'message':       f'"{event_name}" added with 5-minute reminder.',
        }

    except FileNotFoundError as e:
        return {'success': False, 'message': str(e)}
    except HttpError as e:
        return {'success': False, 'message': f'Google Calendar error: {e}'}
    except Exception as e:
        return {'success': False, 'message': f'Error: {e}'}


# ── Quick test ──
if __name__ == "__main__":
    print("Testing Google Calendar...\n")
    r = add_event_to_calendar("EventLink Test", "June 20, 2026", "10:00 AM", "Main Hall", "Test event.")
    print("✓ Success! Link:", r['calendar_link']) if r['success'] else print("✗", r['message'])