"""How Oread fits Wepwawet Veil, the house router: its x-wepwawet section (the Wepwawet standard,
version 2: github.com/coderpigsfly/wepwawet_standard). It's added to Oread's OpenAPI document
(/openapi.json), so the router lays Oread out from Oread's own description, not from its code.
It describes Oread itself, so it lives with Oread's code rather than in its settings."""

WEPWAWET = {
    "version": 2,
    "title": "Oread",
    "spoken": "Oread",                 # what it's called out loud (expectation 1)
    "role": "speech",
    # its people are kept by Oread itself (expectation 15): read them live
    "data": {"kind": "record"},
    # the sound it takes in (expectation 16): the human voice today. The range it moves to, and the
    # acoustic types it handles there, are added when they're set (dev-house-router #23)
    "hears": {"range": "human voice", "path": ["airborne"]},
    "tabs": {"commands": True, "voice_map": False, "clean_up": False, "lists": True, "options": True},
    "auth": {"in": "header", "name": "Authorization", "prefix": "Bearer "},
    "offers": {
        "who_spoke": {
            "title": "Who spoke",
            "description": "Oread names the speaker of each request (speaker ID).",
            "ways": {
                "wyoming": "in the audio path (the router passes the audio through and reads Oread's answer)",
                "api": "Oread's API (the router asks after each request; needs a reviewer token)",
                "sensor": "the sensor Oread sets in Home Assistant",
            },
        },
    },
    "lists": {
        "people": {"from": "GET /profiles", "id": "name", "name": "name", "house": "people"},
    },
}


def described(spec: dict) -> dict:
    """Oread's OpenAPI document with its x-wepwawet section."""
    return dict(spec, **{"x-wepwawet": WEPWAWET})
