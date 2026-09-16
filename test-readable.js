// Self-check for readable() in ui.html: run `node test-readable.js`.
// It pulls the function out of the page it actually ships in, so it cannot
// drift from the deployed copy.
const fs = require('fs');
const page = fs.readFileSync(__dirname + '/ui.html', 'utf8');
const start = page.indexOf('// ---------- spoken text -> readable text');
const end = page.indexOf('// ---------- inspector ----------');
eval(page.slice(start, end));

const cases = [
  // straight from the session's own TTS logs
  ["on September thirteenth,", "on September 13th,"],
  ["twenty twenty six.", "2026."],
  ["in two thousand twenty six", "in 2026"],
  ["The Spanish Grand Prix in two thousand twenty six took place",
   "The Spanish Grand Prix in 2026 took place"],
  ["starting at three thirty.", "starting at 3:30."],
  ["Their next match is against Atlético Madrid on Sunday at ten fifteen PM.",
   "Their next match is against Atlético Madrid on Sunday at 10:15 PM."],
  ["nineteen ninety nine was a good year", "1999 was a good year"],
  ["The match is for the EFL Cup at two thirty am.",
   "The match is for the EFL Cup at 2:30 am."],
  ["The final score was zero to two for Roma.", "The final score was 0 to 2 for Roma."],
  ["Roma won their last game against Torino by scoring two goals.",
   "Roma won their last game against Torino by scoring 2 goals."],
  ["This game took place five days ago at Spotify Camp Nou.",
   "This game took place 5 days ago at Spotify Camp Nou."],
  ["Chelsea's next game is against Brentford. This Premier League match takes place this Saturday at three am.",
   "Chelsea's next game is against Brentford. This Premier League match takes place this Saturday at 3 am."],
  ["Max Verstappen finished second and Lando Norris came in third.",
   "Max Verstappen finished 2nd and Lando Norris came in 3rd."],
  ["one thousand eight hundred four", "1,804"],
  ["seventeen thousand six hundred forty rupiah", "17,640 rupiah"],
  ["zero point eight five", "0.85"],
  ["nineteen ninety nine", "1999"],
  ["twenty percent", "20%"],
  ["twenty three degrees", "23°"],
  // must NOT be mangled
  ["one of the drivers retired", "one of the drivers retired"],
  ["He drove for Ferrari and set the fastest lap.", "He drove for Ferrari and set the fastest lap."],
  ["I do not have that information.", "I do not have that information."],
  ["Andrea Kimi Antonelli won that race driving for Mercedes.",
   "Andrea Kimi Antonelli won that race driving for Mercedes."],
];
let bad = 0;
for (const [inp, want] of cases) {
  const got = readable(inp);
  const ok = got === want;
  if (!ok) bad++;
  console.log(ok ? 'ok  ' : 'FAIL', JSON.stringify(got), ok ? '' : ' want ' + JSON.stringify(want));
}
console.log(bad ? `\n${bad} FAILED` : '\nall pass');

// the bubble-level cases: a run split across clauses must still convert
const joined = [
 ["was 4 goals to one against Rayo Vallecano", "was 4 goals to 1 against Rayo Vallecano"],
 ["they won by two goals to one", "they won by 2 goals to 1"],
 ["it came down to one of the drivers", "it came down to one of the drivers"],
 ["They won two to one after playing six days ago.", "They won 2 to 1 after playing 6 days ago."],
 ["one to two", "1 to 2"],
 ["may be out of date.The last confirmed result was Barcelona.",
  "may be out of date. The last confirmed result was Barcelona."],
 ["The rate is 23.754 today.", "The rate is 23.754 today."],
 ["He finished first with a time of one hour thirty four minutes twenty three point seven five four seconds.",
  "He finished 1st with a time of 1 hour 34 minutes 23.754 seconds."],
 ["The rate is zero point zero zero one eight zero four.", "The rate is 0.001804."],
 ["Five thousand Taiwan dollars is about two million six hundred thousand rupiah.",
  "5,000 Taiwan dollars is about 2,600,000 rupiah."],
];
let bad2 = 0;
for (const [inp, want] of joined) {
  const got = readable(inp);
  if (got !== want) { bad2++; console.log('FAIL', JSON.stringify(got), 'want', JSON.stringify(want)); }
  else console.log('ok  ', JSON.stringify(got));
}
console.log(bad2 ? `${bad2} FAILED` : 'joined all pass');

if (bad || bad2) process.exit(1);
