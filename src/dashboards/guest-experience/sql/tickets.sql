-- One row per support chat. The topic comes from keywords in the guest's first message (a simple match, checked in
-- this order). Each labelled tone is grouped into a mood: negative, neutral or positive.
WITH t AS (
  SELECT
    s.ticket_id,
    s.support_agent_id                                       AS agent,
    TO_DATE(s.created_at)                                    AS opened,
    LOWER(element_at(FILTER(s.messages, m -> m.sender = 'user'), 1).message)    AS first_text,
    LOWER(element_at(FILTER(s.messages, m -> m.sender = 'user'), 1).sentiment)  AS first_tone,
    LOWER(element_at(FILTER(s.messages, m -> m.sender = 'user'), -1).sentiment) AS last_tone,
    SIZE(s.messages)                                         AS messages
  FROM samples.wanderbricks.customer_support_logs AS s
)
SELECT
  ticket_id,
  agent,
  DATE_FORMAT(opened, 'yyyy-MM') AS month,
  messages,
  CASE
    WHEN first_text RLIKE 'refund|compensat|cancel'                        THEN 'Refunds and cancellations'
    WHEN first_text RLIKE 'payout|payment|charge|invoice|billing'          THEN 'Payments and payouts'
    WHEN first_text RLIKE 'clean|dirty|trash|stain|pest|smell'             THEN 'Cleanliness'
    WHEN first_text RLIKE 'photo|listing|description|match|misled'         THEN 'Listing accuracy'
    WHEN first_text RLIKE 'log ?in|password|account|verif|sign up|identity' THEN 'Account and sign-in'
    WHEN first_text RLIKE 'change|modify|dates|add .*guests|extend'        THEN 'Changing a booking'
    WHEN first_text RLIKE 'book|reserv|confirm|double'                     THEN 'Booking problems'
    WHEN first_text RLIKE 'secur|safety|emergency|suspicious|camera'       THEN 'Safety and security'
    WHEN first_text RLIKE 'wi-?fi|internet|kitchen|stove|amenit|broken'    THEN 'Amenities and Wi-Fi'
    WHEN first_text RLIKE 'host|check-?in|check-?out|key|access|noise|neighbo' THEN 'Host and stay'
    WHEN first_text RLIKE 'japan|language|translat|local'                  THEN 'Travel help'
    ELSE 'Other'
  END AS topic,
  first_tone,
  last_tone,
  CASE WHEN first_tone IN ('neutral') THEN 'neutral'
       WHEN first_tone IN ('positive', 'friendly', 'optimistic', 'agreeable', 'aggreeable', 'caring', 'helpful', 'sincere', 'trying to difuse tension') THEN 'positive'
       ELSE 'negative' END AS first_mood,
  CASE WHEN last_tone IN ('neutral') THEN 'neutral'
       WHEN last_tone IN ('positive', 'friendly', 'optimistic', 'agreeable', 'aggreeable', 'caring', 'helpful', 'sincere', 'trying to difuse tension') THEN 'positive'
       ELSE 'negative' END AS last_mood
FROM t
ORDER BY ticket_id
