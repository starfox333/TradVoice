## MISTVALE — a tiny original story, made for the TradUp trailer.
## Everything here (story, characters, pictures) was created for TradUp. Nothing comes from another game.

define e = Character("Elda", color="#f2c46d")
define n = Character(None, what_italic=True)

define config.default_text_cps = 40

## Mist that drifts slowly across the screen.
image fog drift:
    "fog"
    xanchor 0 yanchor 0 ypos 0
    xpos 0
    linear 40.0 xpos -1920
    xpos 0
    repeat

## The lighthouse beam breathes softly.
image beam glow:
    "beam"
    alpha 0.55
    ease 2.5 alpha 1.0
    ease 2.5 alpha 0.55
    repeat

transform sign_pos:
    xalign 0.78
    yalign 0.42

## No title screen: the story starts right away.
label main_menu:
    return

label start:

    scene bg harbor
    show beam glow
    show fog drift
    with fade

    n "The fog rolled in from the sea, thick and silver, swallowing the little harbor whole."

    n "Somewhere above the rooftops, a light was turning."

    show elda at left with dissolve

    e "Welcome to Mistvale, traveler. You picked a strange night to arrive."

    e "The old lighthouse has been dark for a hundred years... and tonight, it's shining."

    e "I'm Elda. I used to keep that light, a long time ago."

    e "Nobody has climbed those stairs since the storm. Nobody but me."

    n "She lifted her lantern, and for a moment the fog seemed to step back."

    e "The fishermen say the light is calling someone home."

    e "I think it's calling you."

    menu:
        e "So, where will you go?"

        "Go to the lighthouse":
            jump lighthouse

        "Stay at the tavern":
            jump tavern


label tavern:

    show sign tavern at sign_pos with dissolve

    n "A wooden sign creaked in the wind. Warm light spilled from the windows below it."

    e "The Rusty Anchor! Best fish stew on the whole coast."

    e "Go on, rest here tonight. The lighthouse will still be shining tomorrow."

    e "...At least, I hope it will."

    jump ending


label lighthouse:

    scene bg lamp
    show fog drift
    with fade

    n "The stairs went up and up, spiraling into the dark."

    show elda at left with dissolve

    e "Careful, the steps are slippery. The sea likes to sneak in."

    n "At the very top, the great lamp was burning, though no one had lit it."

    e "Do you see it? There, beyond the glass..."

    e "A ship. Lost in the fog, all these years."

    e "Let's bring it home."

    jump ending


label ending:

    scene black with dissolve

    n "That night, for the first time in a hundred years, the bell of Mistvale rang."

    n "Thank you for playing!"

    $ renpy.quit()
