// Desk buddy settings. After editing, run ~/deskbuddy/deploy.sh on the laptop.
// The dashboard on the laptop (http://127.0.0.1:8765) overrides night, brightness, sounds, talk,
// fastDictation and stretchEveryMin; the values here are only used until the phone first hears from it.
window.BUDDY_CONFIG = {
  name: "Chip",
  location: { name: "New Delhi", lat: 28.60, lon: 77.20 }, // from GNOME Weather on the laptop
  night: { start: "23:00", end: "06:30" },  // buddy sleeps and dims the screen
  brightness: { day: 90, night: 3 },         // 0–255
  sounds: true,                              // little chirps when you tap or pet it
  talk: true,                                // speaks reminders aloud (never at night)
  fastDictation: false,                      // hold-to-talk: false = better Hinglish (~6 s), true = faster (~3 s)
  stretchEveryMin: 50,                       // nudge after this long at the laptop without a break
  laptop: "http://127.0.0.1:8765",           // laptop bridge, reached through an ssh tunnel to Termux
};
