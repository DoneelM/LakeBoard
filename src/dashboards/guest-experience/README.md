# Guest Experience (sample)

A sample dashboard over the reviews and support chats in `samples.wanderbricks`. It shows text-derived measures in
SQL (topics from keywords, moods from labelled tones in nested chat messages) and a custom mood-flow chart.

## What it shows

- **KPI tiles**: reviews, share of 4 stars or more, share of 1 star, support chats and agents, and the share of chats
  where the guest ended calmer, or more upset, than they started.
- **Reviews** (the Destination filter applies here): reviews per month, the star distribution, best-rated
  destinations, destinations with the most low ratings (under 2.5) and the comments guests leave most.
- **Support chats** (all destinations; chats aren't linked to a property): why guests get in touch (topic, coloured
  by the share that ended upset), how the guest's mood changes from first to last message, the tone of guests and
  agents, and a league table of the 50 agents.

## Data

`samples.wanderbricks.reviews` (99,317 not deleted, March 2023 to July 2025) and
`samples.wanderbricks.customer_support_logs` (1,900 chats of 4 messages each, October 2022 to July 2025). The sample's
review comments come from 15 phrases, so they rank cleanly. Support messages carry a tone label; tones are grouped into
negative, neutral and positive moods in `sql/tickets.sql`. Topics are a keyword match on the guest's first message,
checked in order; 82 chats (4%) match none and show as Other. Names and contact details are never read.

| Dataset | SQL | Rows | Parameters |
|---|---|---|---|
| `destinations` | `sql/destinations.sql` | 42 | none |
| `monthly` | `sql/monthly.sql` | 26 | `destination_id` |
| `stars` | `sql/stars.sql` | 5 | `destination_id` |
| `comments` | `sql/comments.sql` | 15 | `destination_id` |
| `tickets` | `sql/tickets.sql` | 1,900 | none |
| `tones` | `sql/tones.sql` | about 30 | none |

## How the numbers were checked

Against direct queries: 99,793 reviews of which 476 are deleted (99,317 shown); 7,600 chat messages, 3,800 from guests
and 3,800 from agents; 50 support agents.
