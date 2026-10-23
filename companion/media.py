"""Messages based on native Music evidence, never inferred from a visible window."""
import re

SUFFIX = re.compile(r'\s*(?:\((?:feat|ft|with|featuring)\.?[^)]*\)|\[(?:feat|ft|with|featuring)\.?[^\]]*\]|\((?:[^)]*\b(?:remaster(?:ed)?|version|edit|mix|live|mono|stereo)\b[^)]*)\)|\s-\s.*\b(?:remaster(?:ed)?|version|edit|mix|live)\b.*)$', re.I)


def base_title(name):
    """'Far Away (feat. A$AP Rocky)' → 'far away': the title without credits or version tags."""
    previous = None
    name = name or ''
    while previous != name:
        previous, name = name, SUFFIX.sub('', name)
    return ' '.join(re.sub(r'[^\w\s]', ' ', name.casefold()).split())


def near_match(result, query, artist=''):
    """The one library track whose base title equals the request, or None.

    Lets "far away" play "Far Away (feat. A$AP Rocky)" while still refusing to
    guess among several different tracks."""
    if result.get('outcome') != 'not_found':
        return None
    wanted = base_title(query)
    found = {(item.get('name', ''), item.get('artist', '')) for item in result.get('candidates', [])
             if base_title(item.get('name', '')) == wanted and (not artist or artist.casefold() in item.get('artist', '').casefold())}
    return found.pop() if wanted and len(found) == 1 else None


def split_artist(query, artist=''):
    """'Last Christmas by Wham' → ('Last Christmas', 'Wham') when no artist was given."""
    if artist or not isinstance(query, str):
        return query, artist
    match = re.match(r'^(.+?)\s+by\s+(.+)$', query.strip(), re.I)
    return (match.group(1).strip(), match.group(2).strip()) if match else (query, artist)

def describe_music(state):
    player = state.get('player_state')
    if player == 'not_running':
        return 'Music is not running. Playback in other apps or browser tabs has not been checked.'
    if player not in ('playing', 'paused', 'stopped', 'fast forwarding', 'rewinding'):
        return 'I could not read Music’s playback state. Playback in other apps has not been checked.'
    track = state.get('track', {})
    name = track.get('name') or 'an unidentified track'
    artist = ' by '+track['artist'] if track.get('artist') else ''
    if player == 'playing':
        return 'Music reports it is playing '+name+artist+'.'
    if player == 'paused':
        return 'Music is paused'+(' on '+name+artist if track.get('name') else '')+'. Other apps have not been checked.'
    return 'Music reports '+player+'. Other apps have not been checked.'


def describe_play_result(result):
    outcome = result.get('outcome')
    if outcome in ('not_found', 'ambiguous', 'too_many'):
        candidates = result.get('candidates', [])[:5]
        choices = '; '.join(item.get('name', '')+(' by '+item['artist'] if item.get('artist') else '') for item in candidates)
        if outcome == 'not_found':
            if result.get('apple_music_search'):
                return 'That song is not in your library, so I opened Apple Music search for it and will play the top result.'
            return 'That song is not in your Music library, so nothing was played.'+(' Close matches: '+choices+'.' if choices else '')
        return 'Several library tracks match. Nothing was played. Specify the title and artist.'+(' Matches: '+choices if choices else '')
    if result.get('play_submitted') and result.get('requested_id') and result.get('track', {}).get('id') == result['requested_id'] and result.get('player_state') == 'playing':
        return describe_music(result)
    return 'The play request was sent, but playback of the requested track is not confirmed. '+describe_music(result)
