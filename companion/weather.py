"""The weather, answered in code from Open-Meteo (no key, no account).

Only the place name goes out (to find its coordinates), then the coordinates (for the
forecast). With no place named, the user's saved home place is used, else the city of this
Mac's time zone ("Europe/Bucharest" → Bucharest), which needs no location access.
"""
import datetime
import json
import re
import os
import urllib.parse
import urllib.request

GEOCODE = 'https://geocoding-api.open-meteo.com/v1/search?'
FORECAST = 'https://api.open-meteo.com/v1/forecast?'

# WMO weather codes, as Open-Meteo reports them.
CONDITIONS = {0: 'clear', 1: 'mostly clear', 2: 'partly cloudy', 3: 'cloudy', 45: 'foggy', 48: 'foggy',
              51: 'drizzly', 53: 'drizzly', 55: 'drizzly', 56: 'freezing drizzle', 57: 'freezing drizzle',
              61: 'light rain', 63: 'rain', 65: 'heavy rain', 66: 'freezing rain', 67: 'freezing rain',
              71: 'light snow', 73: 'snow', 75: 'heavy snow', 77: 'snow grains', 80: 'showers', 81: 'showers',
              82: 'heavy showers', 85: 'snow showers', 86: 'snow showers', 95: 'thunderstorms', 96: 'thunderstorms',
              99: 'thunderstorms'}
WET = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


class WeatherError(Exception):
    pass


def fetch_json(url, timeout=5):
    request = urllib.request.Request(url, headers={'User-Agent': 'A11y-desktop-companion/1.0 (https://github.com/iediot/a11y; accessibility assistant)'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read(500_000))
    except (OSError, ValueError) as error:
        raise WeatherError('I couldn’t reach the weather service just now.') from error


def timezone_name():
    """The Mac's time zone (e.g. Europe/Bucharest), from TZ or /etc/localtime."""
    if os.getenv('TZ', '').count('/'):
        return os.getenv('TZ')
    try:
        target = os.path.realpath('/etc/localtime')
        if 'zoneinfo/' in target:
            return target.split('zoneinfo/', 1)[1]
    except OSError:
        pass
    return ''


def home_place(saved=''):
    """Where "the weather" means: a saved place, else this Mac's time-zone city."""
    if saved.strip():
        return saved.strip()
    zone = timezone_name()
    city = zone.rsplit('/', 1)[-1].replace('_', ' ') if '/' in zone else ''
    return city


def locate(place):
    """(name, country, latitude, longitude) for a place name."""
    found = fetch_json(GEOCODE+urllib.parse.urlencode({'name': place, 'count': 1, 'language': 'en', 'format': 'json'}))
    results = found.get('results') if isinstance(found, dict) else None
    if not results:
        raise WeatherError(f'I couldn’t find a place called {place}.')
    best = results[0]
    return best.get('name', place), best.get('country', ''), float(best['latitude']), float(best['longitude'])


def day_offset(when, today):
    """0 for now/today, 1 for tomorrow, 2-6 for a weekday ahead; None if not understood."""
    text = (when or '').strip().casefold()
    if text in ('', 'now', 'today', 'tonight', 'this evening', 'this afternoon', 'this morning'):
        return 0
    if 'tomorrow' in text:
        return 1
    date = re.search(r'\d{4}-\d{2}-\d{2}', text)
    if date:
        try:
            return (datetime.date.fromisoformat(date.group(0))-today).days
        except ValueError:
            return None
    for index, name in enumerate(WEEKDAYS):
        if re.search(r'\b'+name[:3], text):  # "friday", "this Friday", "on fri"
            return (index-today.weekday()) % 7 or 7
    return None


def forecast(place, when='now'):
    """{'place', 'sentence', ...} for a place and a day (now, today, tomorrow, a weekday)."""
    name, country, latitude, longitude = locate(place)
    data = fetch_json(FORECAST+urllib.parse.urlencode({
        'latitude': latitude, 'longitude': longitude, 'timezone': 'auto', 'forecast_days': 8,
        'current': 'temperature_2m,weather_code,wind_speed_10m',
        'hourly': 'precipitation_probability,weather_code',
        'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max'}))
    try:
        today = datetime.date.fromisoformat(data['daily']['time'][0])
    except (KeyError, IndexError, TypeError, ValueError):
        raise WeatherError('The weather service sent something I couldn’t read.') from None
    offset = day_offset(when, today)
    if offset is None or not 0 <= offset < len(data['daily']['time']):
        raise WeatherError('I can only see the weather for the next week.')
    return {'place': name, 'country': country, 'sentence': describe(name, data, offset, when)}


def describe(name, data, offset, when):
    daily = data['daily']
    high, low = round(daily['temperature_2m_max'][offset]), round(daily['temperature_2m_min'][offset])
    rain = daily.get('precipitation_probability_max', [None]*8)[offset]
    if offset == 0 and (when or 'now').casefold() in ('', 'now', 'today'):
        current = data.get('current', {})
        temperature = round(current.get('temperature_2m', high))
        condition = CONDITIONS.get(current.get('weather_code'), 'mixed')
        sentence = f'{temperature}°C and {condition} in {name}'
        later = wet_hour(data)
        if later is not None and condition not in ('light rain', 'rain', 'heavy rain', 'showers', 'heavy showers', 'drizzly'):
            sentence += f', with rain likely around {later}'
        return sentence+f'. Today goes from {low}° to {high}°.'
    day = 'Tomorrow' if offset == 1 else datetime.date.fromisoformat(daily['time'][offset]).strftime('%A')
    condition = CONDITIONS.get(daily['weather_code'][offset], 'mixed')
    sentence = f'{day} in {name}: {condition}, {low}° to {high}°C'
    if isinstance(rain, (int, float)) and rain >= 40 and daily['weather_code'][offset] not in WET:
        sentence += f', {round(rain)}% chance of rain'
    return sentence+'.'


def wet_hour(data):
    """The first hour later today with a 60%+ chance of rain, as '6 pm'."""
    hourly = data.get('hourly', {})
    now = (data.get('current') or {}).get('time', '')
    for time, chance in zip(hourly.get('time', []), hourly.get('precipitation_probability', [])):
        if time[:10] != now[:10] or time <= now:
            continue
        if isinstance(chance, (int, float)) and chance >= 60:
            hour = int(time[11:13])
            return f'{hour % 12 or 12} {"am" if hour < 12 else "pm"}'
    return None


# Words a router puts where the place goes ("weather today"): never a place. "today" was geocoded to a
# town called Todaya (live).
NOT_A_PLACE = re.compile(r'^(?:(?:right\s+)?now|today|tonight|tomorrow|this\s+(?:week|weekend|morning|afternoon|evening)|'
                         r'(?:the\s+)?weekend|here|outside|currently|later|soon|my\s+(?:area|city|location)|local(?:ly)?)$', re.I)


def place_named(target):
    """The place in a router's target, '' when it names only a time or "here"."""
    target = (target or '').strip(' ?.!')
    return '' if NOT_A_PLACE.match(target) else target


def places(target, request):
    """The places a weather question names: "Lima or Nairobi" → two of them."""
    parts = [p.strip(' ?.!') for p in re.split(r'\s*(?:,|\bor\b|\bvs\.?|\bversus\b|\band\b)\s*', target or '') if p.strip(' ?.!')]
    if len(parts) < 2:
        # The router often names only one: "warmer in Lima or Nairobi" also in the request's own words.
        match = re.search(r'\bin\s+([A-Z][\w\-]+(?:\s+[A-Z][\w\-]+)?)\s+(?:or|vs\.?|versus|and)\s+([A-Z][\w\-]+(?:\s+[A-Z][\w\-]+)?)', request)
        if match:
            parts = [match.group(1), match.group(2)]
    return parts[:3]


def compare(names):
    """Which of a few places is warmer now, in one sentence."""
    readings = []
    for name in names:
        place, _, latitude, longitude = locate(name)
        data = fetch_json(FORECAST+urllib.parse.urlencode({'latitude': latitude, 'longitude': longitude, 'timezone': 'auto',
                                                           'current': 'temperature_2m'}))
        readings.append((round(data['current']['temperature_2m']), place))
    readings.sort(reverse=True)
    (warm, first), (cold, second) = readings[0], readings[-1]
    if warm == cold:
        return f'{first} and {second} are both about {warm}°C right now.'
    return f'{first} is warmer: {warm}°C, against {cold}°C in {second}.'
