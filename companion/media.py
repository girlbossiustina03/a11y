"""Messages based on native Music evidence, never inferred from a visible window."""
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
            return 'No unique exact song match was found in your Music library. Nothing was played. This tool does not search the Apple Music subscription catalog.'+(' Possible matches: '+choices if choices else '')
        return 'Several library tracks match. Nothing was played. Specify the title and artist.'+(' Matches: '+choices if choices else '')
    if result.get('play_submitted') and result.get('requested_id') and result.get('track', {}).get('id') == result['requested_id'] and result.get('player_state') == 'playing':
        return describe_music(result)
    return 'The play request was sent, but playback of the requested track is not confirmed. '+describe_music(result)
