# Ccr-gift
# Gift Rewards Bot

A Telegram gift rewards bot with force-channel join, gift key unlocking, SQLite
storage, and admin commands.

## Setup

1. Create a bot with `@BotFather` and copy its token.
2. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and set `BOT_TOKEN`, `OWNER_ID`, and
   `FORCE_JOIN_CHANNEL`.
4. Add the bot as an administrator to the configured channel.
5. Start the bot:

   ```bash
   python bot.py
   ```

## User flow

- `/start` shows the channel join screen.
- `VERIFY JOIN` checks channel membership.
- Users select a gift and enter its private key.
- The gift content is shown only after the correct key is entered.

## Admin commands

| Command | Usage |
| --- | --- |
| `/addgift` | `/addgift Gift Name::Gift content` |
| `/delgift` | `/delgift GIFT_ID` |
| `/setkey` | `/setkey GIFT_ID KEY` |
| `/addadmin` | `/addadmin USER_ID` |
| `/broadcast` | `/broadcast Message text` |
| `/stats` | `/stats` |
| `/setchannel` | `/setchannel @channel_username` |

Only `OWNER_ID` can add admins. `/setchannel -100...` also accepts a numeric
channel ID.