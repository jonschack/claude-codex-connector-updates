# User TODO

## Enable daily email of the report

The emailer module and `daily --email-to` wiring are in place but disabled. To turn email on:

1. **Create a Gmail app password** at https://myaccount.google.com/apppasswords
   (Requires 2FA enabled on the Google account. The output is a 16-character string.)

2. **Edit the launchd plist** at `scripts/com.openclaw.mcp-newsletter.plist`:
   - Replace `REPLACE_WITH_YOUR_GMAIL_ADDRESS` with the sender Gmail address.
   - Replace `REPLACE_WITH_GMAIL_APP_PASSWORD` with the app password from step 1.
   - Remove `<string>--skip-email</string>` from `ProgramArguments` so the daily run actually sends.

3. **Reload the launchd job:**
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.openclaw.mcp-newsletter.plist
   cp scripts/com.openclaw.mcp-newsletter.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.openclaw.mcp-newsletter.plist
   ```

4. **Test before waiting for 7 AM:**
   ```bash
   launchctl start com.openclaw.mcp-newsletter
   tail -f tmp/launchd.err.log
   ```

5. **Do not commit the plist with the password.** Either:
   - Add `scripts/com.openclaw.mcp-newsletter.plist` to `.gitignore`, or
   - Keep the only filled-in copy in `~/Library/LaunchAgents/` and leave the repo copy with placeholders.

The recipient is already set to `internonedirection@automationinterns.com`. Change `MCP_NEWSLETTER_EMAIL_TO` in the plist to send elsewhere.

Manual send (any date):
```bash
MCP_NEWSLETTER_EMAIL_TO=... MCP_NEWSLETTER_SMTP_USER=... MCP_NEWSLETTER_SMTP_PASSWORD=... \
  python3 -m mcp_newsletter email --date 2026-05-15
```

## Fix hardcoded Codex plugin path

`mcp_newsletter/providers/codex.py:17` defaults to `/Users/jon/.codex/.tmp/plugins`, which doesn't exist on this machine (user is `openclaw`). The collector emits a "marketplace not found" issue every run. Either:
- Set `MCP_NEWSLETTER_CODEX_PLUGIN_ROOT` to your real plugin root in the launchd plist, or
- Change the default in code to `~/.codex/plugins` (or wherever Codex actually stores plugins on this machine).
