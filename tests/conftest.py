import pytest


def synthetic_card(**over):
    """A card record shaped like Scryfall's, with no Wizards content in it."""
    card = {
        "name": "Test Subject", "layout": "normal", "type_line": "Creature — Fixture",
        "oracle_text": "Flying\nWhen this enters, draw a card. (Reminder text goes here.)",
        "flavor_text": "A *fixture* speaks.", "mana_cost": "", "colors": ["U"],
        "power": "2", "toughness": "3", "rarity": "rare", "artist": "Nobody",
        "set": "tst", "collector_number": "1", "illustration_id": "00000000-0000-0000-0000-000000000000",
        "image_uris": {"art_crop": "https://invalid.example/never-fetched.jpg"},
    }
    card.update(over)
    return card


@pytest.fixture
def card():
    return synthetic_card()


@pytest.fixture
def art(tmp_path):
    """A generated placeholder image in the art window's proportions, so nothing is fetched."""
    from PIL import Image
    fn = tmp_path / "art.png"
    im = Image.new("RGB", (284, 200))
    px = im.load()
    for y in range(200):
        for x in range(284):
            px[x, y] = (x * 255 // 283, y * 255 // 199, 128)
    im.save(fn)
    return str(fn)
