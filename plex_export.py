"""
Player -- Plex playlist export (native playlist -> real Plex playlist).

Reuses the underlying mechanism already proven in MusicMind's
plex_playlist.py (plexapi's createPlaylist), but scoped to a
"MusicLounge-" name prefix and an ownership check before ever
deleting anything -- MusicMind's own create_plex_playlist() deletes
*any* Plex playlist matching the target name with no check for
whether it created that playlist in the first place, which is a real
risk if a user has an unrelated Plex-native playlist with the same
name. This module never touches a Plex playlist it didn't create
itself.

See MUSICLOUNGE-PLAYER-V1-SCOPE.md, "Plex playlist export" and
"Precedent check: MusicMind's playlist model" for the reasoning.
"""
import db
import plex_client

EXPORT_PREFIX = "MusicLounge-"


class ExportError(Exception):
    pass


def _namespaced_name(playlist_name):
    return f"{EXPORT_PREFIX}{playlist_name}"


def export_playlist(playlist_id):
    """Exports a native playlist to Plex under the MusicLounge- prefix.

    Create-or-overwrite-by-name, scoped to the namespace only:
      - If a Plex playlist with the namespaced name exists AND it's
        the one we exported before (playlists.exported_ref matches
        its rating_key), delete and recreate it -- this is our own
        object, safe to replace.
      - If a Plex playlist with the namespaced name exists but we've
        never exported this playlist_id to it before (exported_ref is
        NULL or doesn't match), refuse rather than silently
        overwriting something we don't know we own. This is the
        one case MusicMind's version doesn't guard against.
      - If nothing matches the namespaced name, just create it.

    Returns the new Plex rating_key on success. Raises ExportError on
    any refusal or failure, with a message safe to show the admin.
    """
    playlist = db.get_playlist(playlist_id)
    if not playlist:
        raise ExportError("Playlist not found.")
    if playlist["source"] != "native":
        raise ExportError("Only native playlists can be exported -- this one is a Plex-synced mirror already.")

    track_rows = db.get_playlist_tracks(playlist_id)
    if not track_rows:
        raise ExportError("This playlist has no tracks to export yet.")

    plex = plex_client.get_plex()
    export_name = _namespaced_name(playlist["name"])

    existing = None
    for pl in plex.playlists():
        if pl.title == export_name:
            existing = pl
            break

    if existing is not None:
        already_ours = (
            playlist["exported_ref"] is not None
            and str(existing.ratingKey) == str(playlist["exported_ref"])
        )
        if not already_ours:
            raise ExportError(
                f"A Plex playlist named \"{export_name}\" already exists and wasn't "
                f"created by this export. Rename the playlist in Player, or rename/"
                f"remove the existing one in Plex, before exporting."
            )
        existing.delete()

    tracks = []
    missing = []
    for row in track_rows:
        try:
            tracks.append(plex.fetchItem(int(row["track_ref"])))
        except Exception:
            missing.append(row["title"] or row["track_ref"])

    if not tracks:
        raise ExportError("None of this playlist's tracks could be found in Plex anymore.")

    created = plex.createPlaylist(export_name, items=tracks)
    db.mark_playlist_exported(playlist_id, created.ratingKey)

    return {
        "rating_key": created.ratingKey,
        "exported_name": export_name,
        "track_count": len(tracks),
        "missing_tracks": missing,  # surfaced to the admin, not silently dropped
    }
