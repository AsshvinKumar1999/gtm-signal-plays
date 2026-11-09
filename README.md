# GTM Signal Plays

GTM plays built from two free public signals and run in Claude Code, by Asshvin Kumar.

**Live site:** https://asshvinkumar1999.github.io/gtm-signal-plays/

## Play 01: Fresh Capital + Open Role
Find software companies that just told the SEC they raised money (Form D) and are hiring the role your product serves.

- Free public data only: SEC EDGAR, and the public Greenhouse, Lever and Ashby job board APIs. No API keys.
- `plays/01-fresh-capital-open-role/run.py`: Python 3.9+, standard library only.
- The play page has the run receipt, the animated diagram and a copy-paste Claude Code prompt.

```bash
SEC_USER_AGENT="Your Name you@example.com" python3 plays/01-fresh-capital-open-role/run.py --days 7
```

SEC asks every request to include a name and email in the User-Agent and to stay under 10 requests a second. The script does both.
