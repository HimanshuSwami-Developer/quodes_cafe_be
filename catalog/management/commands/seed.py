"""Seed the café: station types, stations, games, FAQs and policies from the design.
Safe to re-run (updates in place)."""
from decimal import Decimal

from django.core.management.base import BaseCommand

from catalog.models import CafeSettings, Game, Station, StationType
from support.models import FAQ, Policy, PolicySection

TYPES = [
    # code, name, spec, seats/station, rate, prefix, cols, stations
    ("PS5", "Station 5", "4K TV · 2 controllers", 2, "150", "S5", 3, 5),
    ("PS4", "Station 4", "Full HD TV · 2 controllers", 2, "100", "S4", 2, 4),
    ("PC", "Gaming PC", "High-refresh monitor · headset", 1, "120", "PC", 5, 10),
]

GAMES = [
    ("EA Sports FC 25", "FC25", "SPORTS", "#0E8A45", "#E3F8EC", ["PS5", "PS4", "PC"], 4),
    ("Valorant", "VAL", "SHOOTER", "#D12F35", "#240C12", ["PC"], 4),
    ("GTA V", "GTA", "OPEN WORLD", "#A35500", "#241808", ["PS5", "PS4", "PC"], 4),
    ("Call of Duty: Warzone", "COD", "SHOOTER", "#6B3CF5", "#071E1D", ["PS5", "PC"], 4),
    ("Tekken 8", "T8", "FIGHTING", "#D6337A", "#210A1E", ["PS5", "PC"], 4),
    ("Forza Horizon 5", "FH5", "RACING", "#7C9CFF", "#0C1230", ["PC"], 4),
    ("Marvel’s Spider-Man 2", "SM2", "ACTION", "#FF8A3D", "#26110A", ["PS5"], 4),
    ("Counter-Strike 2", "CS2", "SHOOTER", "#FFD84A", "#221D06", ["PC"], 4),
]

FAQS = [
    ("How does slot locking work?", "Tap Lock slot and the station is reserved only for you for 10 minutes. Pay and upload your screenshot in that time, or it unlocks for other players."),
    ("What happens after the AI check?", "Your session is provisionally booked. A team member confirms the payment within 2 hours. If that doesn’t happen in time, the slot is released and your payment is kept as credit or refunded."),
    ("Which UPI apps can I use?", "Any UPI app. Scan the QR from another phone, or tap Open in UPI app to pay on the same phone."),
    ("How many players per station?", "Station 5 and Station 4 consoles take up to 2 players each. Gaming PCs are 1 player each. Book up to 4 seats together."),
    ("Can I extend my session?", "Yes, if the next slot on your station is free. Ask at the desk or rebook from the app."),
    ("Do I need my own game account?", "For online games like Valorant, log in with your own account. Offline and local multiplayer games are ready to play."),
    ("What if I arrive late?", "Your session still ends at the booked time. Arriving after [X] minutes may release your station."),
]

POLICIES = [
    ("house", "House rules", [
        ("Respect the gear", "Handle controllers, headsets and PCs with care. Damage from misuse is charged at repair cost."),
        ("Time is time", "Sessions start and end at the booked time. Late arrival doesn’t extend your slot."),
        ("No food at stations", "Snacks and drinks stay in the lounge area to keep stations clean."),
        ("Fair play", "No cheats, mods or toxic behaviour. Staff may end a session without refund."),
        ("Your accounts", "Log out of personal game accounts before you leave. We’re not responsible for saved logins."),
    ]),
    ("privacy", "Privacy", [
        ("What we collect", "Name, email, phone, gamertag, bookings and the payment screenshots you upload."),
        ("Screenshots", "Used only to verify payments, by our AI and our team, and deleted after [X] days."),
        ("Sharing", "We never sell your data. Booking details are seen only by Quodes staff."),
        ("Your rights", "Ask Support for a copy of your data or to delete your account anytime."),
    ]),
    ("refunds", "Refunds", [
        ("Cancel early", "Cancel at least [X] hours before your session for a full refund or credit."),
        ("Late cancel", "Cancellations after that get [X]% back as game credit."),
        ("Slot released", "If team verification doesn’t finish within 2 hours, your payment becomes credit or is refunded on request."),
        ("Station down", "If your station has a fault, we move you to another or refund the lost time."),
        ("Timeline", "Refunds go back to your UPI account within [X] working days."),
    ]),
]


class Command(BaseCommand):
    help = "Seed station types, stations, games, FAQs and policies."

    def handle(self, *args, **opts):
        CafeSettings.get()
        types = {}
        for i, (code, name, spec, seats, rate, prefix, cols, count) in enumerate(TYPES):
            t, _ = StationType.objects.update_or_create(code=code, defaults=dict(
                name=name, spec=spec, seats_per_station=seats, hourly_rate=Decimal(rate),
                seat_prefix=prefix, grid_cols=cols, sort=i))
            types[code] = t
            for n in range(1, count + 1):
                st, _ = Station.objects.get_or_create(type=t, number=n)
                st.save()  # ensures seats exist
        for i, (name, mono, genre, hue, deep, plats, mx) in enumerate(GAMES):
            g, _ = Game.objects.update_or_create(mono=mono, defaults=dict(
                name=name, genre=genre, hue=hue, deep=deep, max_players=mx, sort=i))
            g.platforms.set([types[p] for p in plats])
        for i, (q, a) in enumerate(FAQS):
            FAQ.objects.update_or_create(question=q, defaults=dict(answer=a, sort=i))
        for i, (key, title, sections) in enumerate(POLICIES):
            p, _ = Policy.objects.update_or_create(key=key, defaults=dict(title=title, sort=i))
            p.sections.all().delete()
            for j, (h, b) in enumerate(sections):
                PolicySection.objects.create(policy=p, heading=h, body=b, sort=j)
        self.stdout.write(self.style.SUCCESS("Seeded café data."))
