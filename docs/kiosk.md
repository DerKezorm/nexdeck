# Kiosk displays

A kiosk link shows one board without a sign-in: for a wall tablet, a
television or a monitor in the rack room.

Board menu > Kiosk > Create kiosk link. The full link is shown once; open it
on the display. It looks like `https://deck.example.com/k/nk_…`. Once the
display is in, its address shows `/k` alone: the token waits on the display
itself, not in its browser history.

| Setting | Effect |
|---|---|
| Cycle pages | Switches to the next page every so many seconds. `0` stays on one page. |
| Dim from / until | Darkens the display during that window, e.g. 23:00 to 06:30. |
| Allow actions | Buttons on the cards work on the display. Off by default: anyone at the display could restart containers otherwise. |

The token carries no session. It can read the board, its live stream, its
icons and uploaded pictures, and nothing else. Revoke it in the same menu; the display then shows
that the link is no longer valid.

Tablets: add the link to the home screen; Fully Kiosk Browser and similar apps
keep the screen on. The board uses the dark theme on displays, in the colour
theme, accent, card style and style sheet chosen under Appearance. While a card
is down it glows red and the background turns faintly red, so a display says
it from across the room.

A link can let the display rest after a few minutes without a touch: the
time, the day, the weather of the board's first weather card and what is down,
large on black. The picture moves a few pixels every minute, so a screen that
shows it all night does not burn it in. A touch brings the board back.
