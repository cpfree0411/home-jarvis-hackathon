"""Synthetic English sample stories (fiction written for this project).

Each sample carries a prepared neutral summary and prepared demo-fixture answers.
They are used only when a seat or the organizer has no live provider configured,
and the UI always labels them as prepared demo content, never as live AI output.
"""
from __future__ import annotations

import hashlib

SAMPLES = [
    {
        "id": "haircut",
        "teaser": "The haircut question",
        "text": (
            "So my girlfriend Maya got a really dramatic haircut on Saturday. She went from long hair to a "
            "short bob with blunt bangs. When she got home she spun around and asked me, honestly, do you "
            "like it? And honestly... I don't love it yet. I said it was bold and that I needed a day to get "
            "used to it. She went quiet and later told me she wished I had just said it looked great, because "
            "she can't undo it anyway and she was already nervous. My view is that she asked for honesty and "
            "I was gentle about it. Her view is that when someone asks right after a change they can't reverse, "
            "you lead with support and save the nuance. Which of us handled it better?"
        ),
        "organized": {
            "title": "Honest or supportive about a new haircut?",
            "context": ("Maya got a dramatic haircut, going from long hair to a short bob with bangs. She asked "
                        "her boyfriend whether he honestly liked it. He said it was bold and that he needed a "
                        "day to get used to it. She later said she wished he had simply said it looked great, "
                        "since the cut can't be undone and she was already nervous."),
            "subject": "How to answer a partner who asks for an honest opinion about a change they can't undo",
            "entities": [{"name": "Maya", "role": "girlfriend who got the haircut"},
                         {"name": "the speaker", "role": "boyfriend who answered"}],
            "side_a": {"label": "Gentle honesty",
                       "position": ("She asked for an honest opinion, so a kind but truthful answer such as "
                                    "'it's bold, give me a day' respects the question.")},
            "side_b": {"label": "Lead with support",
                       "position": ("Right after a change that can't be reversed, the answer should lead with "
                                    "reassurance and keep any reservations for later, if at all.")},
        },
        "fixture": {
            "nemotron": {"choice": "B", "strength": "LEAN",
                         "reasoning": "The cut was already done and she was nervous, so the question was mostly a request for reassurance.",
                         "other_side_credit": "He didn't lie and he was kind about it; 'give me a day' is a soft way to be honest.",
                         "suggestion": "Tell her what you do like about it now, and let your opinion catch up over the week."},
            "gpt": {"choice": "A", "strength": "CLOSE",
                    "reasoning": "She explicitly asked for honesty, and his answer was gentle rather than critical.",
                    "other_side_credit": "Timing matters: right after a big change, support is what most people need first.",
                    "suggestion": "Agree that 'honestly?' right after a haircut means 'reassure me', and save critiques for things that can still change."},
            "claude": {"choice": "B", "strength": "LEAN",
                       "reasoning": "When nothing can be changed, honesty mainly adds worry; leading with support costs him little.",
                       "other_side_credit": "Being trustworthy matters, and a reflexive 'it's great' can feel hollow later.",
                       "suggestion": "Name one specific thing you like about the cut, and tell her you'll have a full opinion once it has grown on you."},
        },
    },
    {
        "id": "dinner-bill",
        "teaser": "Splitting the dinner bill",
        "text": (
            "Four of us went out for dinner. Jordan ordered a steak and two cocktails, and the rest of us "
            "had pasta and water. When the bill came Jordan said let's just split it evenly, it's simpler. "
            "Priya said everyone should pay for what they ordered. It came to about twenty dollars "
            "difference per person. Who was being more reasonable?"
        ),
        "organized": {
            "title": "Split evenly or pay for what you ordered?",
            "context": ("Four friends had dinner. Jordan ordered a steak and two cocktails while the others had "
                        "pasta and water. Jordan suggested splitting the bill evenly; Priya suggested everyone "
                        "pay for their own order. The difference was about twenty dollars per person."),
            "subject": "How a group of friends should split a restaurant bill when orders differ a lot",
            "entities": [{"name": "Jordan", "role": "friend who ordered more"},
                         {"name": "Priya", "role": "friend who suggested paying separately"}],
            "side_a": {"label": "Split it evenly",
                       "position": "An even split is quick and simple and avoids counting every item at the table."},
            "side_b": {"label": "Pay for your own order",
                       "position": "When orders differ by about twenty dollars a head, each person should pay for what they ordered."},
        },
        "fixture": {
            "nemotron": {"choice": "B", "strength": "STRONG",
                         "reasoning": "A twenty-dollar gap per person is too big to call rounding; the others would be paying for Jordan's drinks.",
                         "other_side_credit": "Even splits do keep things simple when orders are close.",
                         "suggestion": "Split the shared parts evenly and let whoever ordered drinks or extras cover those."},
            "gpt": {"choice": "B", "strength": "LEAN",
                    "reasoning": "Paying for your own order is fairer when the difference is this large.",
                    "other_side_credit": "Jordan's point about avoiding awkward arithmetic is real.",
                    "suggestion": "Decide before ordering whether it's an even-split night."},
            "claude": {"choice": "B", "strength": "LEAN",
                       "reasoning": "The person who ordered the most proposing an even split puts the cost on everyone else.",
                       "other_side_credit": "Among close friends who take turns, even splits often balance out over time.",
                       "suggestion": "Use itemised splitting tonight, and agree a simple rule for next time."},
        },
    },
    {
        "id": "game-night",
        "teaser": "The board game house rule",
        "text": (
            "At our game night we were playing a board game and Sam wanted to use a house rule that lets "
            "you trade cards with any player, not just neighbours. Alex said we should stick to the official "
            "rulebook because it's the only fair way when new people are playing. Two of the five players "
            "were new. Which way should it go?"
        ),
        "organized": {
            "title": "House rule or official rules at game night?",
            "context": ("Five people played a board game, two of them for the first time. Sam wanted a house rule "
                        "allowing card trades with any player. Alex wanted to follow the official rulebook "
                        "because new players were present."),
            "subject": "Whether to use a familiar house rule or the official rules when new players join",
            "entities": [{"name": "Sam", "role": "player proposing the house rule"},
                         {"name": "Alex", "role": "player preferring the official rules"}],
            "side_a": {"label": "Use the house rule",
                       "position": "The house rule makes trading more open and the game more lively for everyone."},
            "side_b": {"label": "Stick to the rulebook",
                       "position": "With new players at the table, the official rules are the clearest and fairest shared reference."},
        },
        "fixture": {
            "nemotron": {"choice": "B", "strength": "LEAN",
                         "reasoning": "New players can only check the official rules, so those level the field.",
                         "other_side_credit": "A good house rule can make the game more fun once everyone knows it.",
                         "suggestion": "Play the first round by the book, then vote on the house rule."},
            "gpt": {"choice": "A", "strength": "CLOSE",
                    "reasoning": "Open trading is easy to explain and gives new players more ways to take part.",
                    "other_side_credit": "Changing rules on newcomers can feel like the regulars have an edge.",
                    "suggestion": "Explain the house rule before the game starts and let the new players decide."},
            "claude": {"choice": "B", "strength": "LEAN",
                       "reasoning": "Fairness to newcomers matters most at a first game, and the rulebook is neutral ground.",
                       "other_side_credit": "Sam's rule might well make the evening more social.",
                       "suggestion": "Keep a short list of house rules and introduce them in a second game."},
        },
    },
]

BY_ID = {s["id"]: s for s in SAMPLES}


def public_list() -> list[dict]:
    return [{"id": s["id"], "teaser": s["teaser"], "text": s["text"]} for s in SAMPLES]


def fixture_answer(member: str, sample_id: str | None, story_id: str) -> dict:
    """A prepared demo answer. For custom stories it says plainly that it is a placeholder."""
    sample = BY_ID.get(sample_id or "")
    if sample:
        return dict(sample["fixture"][member])
    choice = "A" if int(hashlib.sha256((story_id + member).encode()).hexdigest(), 16) % 2 else "B"
    return {"choice": choice, "strength": "CLOSE",
            "reasoning": "Demo placeholder: no live model is configured for this seat, so this vote was not made by an AI.",
            "other_side_credit": "Both positions deserve a real look; configure a provider to get an actual judgment.",
            "suggestion": "Add an API key or CLI login for this seat and ask again."}
